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


def _requested_edition() -> str:
    """Return the normalized explicit edition, rejecting invalid operator input."""
    raw_value = os.environ.get("GEOLENS_EDITION")
    if raw_value is None:
        # BaseSettings reads bare-metal .env files without exporting their
        # values into os.environ. Fall back to the validated Settings value so
        # the startup guards honor the same contract outside Compose.
        from app.core.config import settings

        raw_value = settings.geolens_edition
    value = (raw_value or "").lower().strip()
    if value not in ("", "community", "enterprise"):
        raise RuntimeError(
            "GEOLENS_EDITION must be unset, 'community', or 'enterprise'. "
            "Refusing to infer an edition from an invalid explicit value."
        )
    return value


@dataclass(frozen=True)
class EditionInfo:
    """Immutable edition descriptor."""

    edition: str
    features: tuple[str, ...] = ()
    # True only when a signed license verified. False for legacy
    # env/extension-detected "enterprise" so ops can tell the two apart.
    licensed: bool = False
    customer: str | None = None
    maintenance_until: datetime | None = None


def init_edition(loaded_extensions: list[str]) -> None:
    """Initialize the edition from a signed license, with backward-compatible
    env/extension auto-detection.

    Resolution order: (1) a valid signed license (``GEOLENS_LICENSE_KEY``) →
    enterprise, the only path that should grant it in production; (2) else,
    if ``GEOLENS_LICENSE_ENFORCE`` is truthy, community regardless of
    ``GEOLENS_EDITION``/loaded extensions — closing the honor-system bypass;
    (3) else the legacy signal — ``GEOLENS_EDITION`` override, else
    enterprise if any extension loaded, logged as a warning since strict
    mode would reject it.
    """
    global _info

    env_val = _requested_edition()
    license_info: LicenseInfo | None = load_license()
    enforce = _is_truthy(os.environ.get("GEOLENS_LICENSE_ENFORCE"))

    if license_info is not None:
        _info = EditionInfo(
            edition="enterprise",
            features=tuple(loaded_extensions),
            licensed=True,
            customer=license_info.customer,
            maintenance_until=license_info.maintenance_until,
        )
        logger.info(
            "Edition: enterprise (licensed)",
            customer=license_info.customer,
            maintenance_until=license_info.maintenance_until.isoformat(),
            extensions=loaded_extensions,
        )
        return

    # No valid license from here on.
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
    """Return the current edition info, defaulting to Community.

    A verified license keeps the installed Enterprise version active after
    maintenance ends. ``maintenance_until`` is available to update and support
    workflows, but it never changes the runtime edition.
    """
    if _info is None:
        return EditionInfo(edition="community", features=())
    return _info


def is_enterprise() -> bool:
    """Return True if running in enterprise edition."""
    return get_edition().edition == "enterprise"


def check_enterprise_overlay_requested(loaded_extensions: list[str]) -> None:
    """Fail loudly when Enterprise is explicitly requested but the overlay is absent.

    BUG-003: the silent OSS fallback was the root cause — an operator sets
    ``GEOLENS_EDITION=enterprise`` and mounts the enterprise directory, but a
    read-only rootfs blocks ``uv add --editable`` from installing it into
    the baked venv; the entrypoint continues silently and the app boots as
    community with no visible error. Called from the app lifespan after
    ``load_extensions()``, so this checks operator intent alone — it
    ignores ``GEOLENS_LICENSE_ENFORCE`` and license state, which decide the
    final edition separately.

    Raises ``RuntimeError`` when ``GEOLENS_EDITION=enterprise`` but
    ``loaded_extensions`` is empty; the remedy is the overlay repo's
    immutable image build, not a runtime ``uv add`` under read-only rootfs.
    """
    env_val = _requested_edition()

    if env_val != "enterprise":
        return

    if loaded_extensions:
        return

    raise RuntimeError(
        "GEOLENS_EDITION=enterprise is set but no enterprise overlay extension "
        "was loaded (the geolens.extensions entry-point group is empty). "
        "A runtime 'uv add --editable' cannot install the overlay under a "
        "read_only container rootfs. "
        "Use the overlay repository's immutable image build, which installs "
        "the locked overlay wheel at build time. "
        "The app is refusing to start as community edition when enterprise "
        "was explicitly requested."
    )


def check_tenancy_mode_supported(loaded_extensions: list[str]) -> None:
    """GUARD-01 edition-half: fail loudly when GEOLENS_TENANCY_MODE=multi_tenant
    but no tenancy-providing overlay is loaded.

    Phase 1207: multi_tenant without an overlay means the isolation layer
    (RLS + session GUC, Phase 1208) cannot be present — serving requests
    without it is an elevation-of-privilege risk (T-1207-06). The full
    RLS-present assertion is deferred to Phase 1208; this check is
    minimal-but-correct for Phase 1207's surface.

    Raises ``RuntimeError`` when multi_tenant mode is set but
    ``loaded_extensions`` is empty.

    References: GUARD-01, TSEAM-03, T-1207-06
    """
    raw_mode = os.environ.get("GEOLENS_TENANCY_MODE")
    if raw_mode is None:
        from app.core.config import settings

        raw_mode = settings.geolens_tenancy_mode
    mode_val = (raw_mode or "").lower().strip()

    if mode_val != "multi_tenant":
        return

    if loaded_extensions:
        return

    raise RuntimeError(
        "GEOLENS_TENANCY_MODE=multi_tenant is set but no overlay extension "
        "was loaded (the geolens.extensions entry-point group is empty). "
        "Multi-tenant mode requires the cloud overlay which provides the "
        "per-tenant isolation layer (RLS + session GUC, Phase 1208). "
        "Without the overlay the app would serve ALL tenants from a single "
        "unscoped database session — a critical isolation failure. "
        "Use the cloud overlay repository's immutable image build. "
        "The app is refusing to start in multi_tenant mode without the "
        "required tenancy isolation layer. "
        "References: GUARD-01, TSEAM-03, T-1207-06."
    )
