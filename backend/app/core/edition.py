"""Edition detection singleton.

The authoritative enterprise signal is a **signed offline license**
(:mod:`app.core.license`). For backward compatibility, the legacy
``GEOLENS_EDITION`` override and loaded-extension auto-detection still apply
*unless* strict enforcement (``GEOLENS_LICENSE_ENFORCE``) is enabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

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
    """Return the current edition info, defaulting to community.

    A *licensed* enterprise edition is re-checked against the license's
    ``expires_at`` on every read, so a long-running / always-on process stops
    unlocking enterprise once the license expires — without needing a restart.
    The legacy env/extension path carries no ``expires_at`` and is unaffected.
    """
    if _info is None:
        return EditionInfo(edition="community", features=())
    if (
        _info.licensed
        and _info.expires_at is not None
        and datetime.now(UTC) >= _info.expires_at
    ):
        return EditionInfo(edition="community", features=_info.features, licensed=False)
    return _info


def is_enterprise() -> bool:
    """Return True if running in enterprise edition."""
    return get_edition().edition == "enterprise"


def check_enterprise_overlay_requested(loaded_extensions: list[str]) -> None:
    """Fail loudly when Enterprise is explicitly requested but the overlay is absent.

    BUG-003 — The silent OSS fallback was the root of the problem: an operator
    sets ``GEOLENS_EDITION=enterprise`` (or relies on the env var path), mounts
    the enterprise directory, but the ``read_only: true`` rootfs prevents
    ``uv add --editable`` from writing into the baked venv. The entrypoint
    silently continues; ``load_extensions()`` finds no entry-points; the app
    boots as community edition with no visible error. Operators believe they are
    running Enterprise while they are on OSS.

    This check is called from the app lifespan *after* ``load_extensions()``
    so the full set of loaded extensions is known before the check runs.

    Resolution order (checked in priority):
    1. No ``GEOLENS_EDITION`` env var set → default OSS → no error (silent, healthy).
    2. ``GEOLENS_EDITION=community`` explicitly → no error.
    3. ``GEOLENS_EDITION=enterprise`` → overlay MUST be loaded (non-empty
       ``loaded_extensions``); if not, raise ``RuntimeError`` so the process
       exits non-zero and the container scheduler marks the pod as failed
       instead of silently serving community features.

    The check intentionally ignores ``GEOLENS_LICENSE_ENFORCE`` and the license
    path — those affect *which* edition is the *final* edition; this check fires
    on the *operator intent signal* alone, before edition resolution.

    Args:
        loaded_extensions: The list of extension names discovered by
            ``load_extensions()`` via the ``geolens.extensions`` entry-point
            group. An empty list means no overlay package registered itself.

    Raises:
        RuntimeError: When Enterprise is explicitly requested via
            ``GEOLENS_EDITION=enterprise`` but no overlay extension is loaded.
            The correct remedy is to use the overlay repository's immutable
            image build rather than attempting a runtime ``uv add`` under a
            read-only rootfs.
    """
    env_val = os.environ.get("GEOLENS_EDITION", "").lower().strip()

    if env_val != "enterprise":
        # Not explicitly requesting enterprise — OSS default or community explicit.
        return

    if loaded_extensions:
        # Enterprise requested and at least one overlay extension is registered.
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

    Phase 1207 surface: a multi_tenant deploy without any overlay extension
    registered means the isolation layer (1208 RLS + session GUC) cannot be
    present. Boot must be refused — serving requests in multi_tenant mode
    without the isolation layer is an elevation-of-privilege risk (T-1207-06).

    Resolution order:
    1. GEOLENS_TENANCY_MODE unset or ``single_tenant`` → no-op (safe default).
    2. GEOLENS_TENANCY_MODE=``multi_tenant`` + at least one overlay loaded
       → passes (the overlay is expected to provide the isolation layer
       in Phase 1208).
    3. GEOLENS_TENANCY_MODE=``multi_tenant`` + no overlays → ``RuntimeError``.

    The full RLS-present assertion (confirming the overlay actually registered
    a tenancy layer) is deferred to Phase 1208. This check is minimal-but-
    correct for Phase 1207's surface.

    Args:
        loaded_extensions: Extension names discovered by ``load_extensions()``.

    Raises:
        RuntimeError: When multi_tenant mode is configured but no overlay is
            loaded — the isolation layer cannot be present without an overlay.

    References: GUARD-01, TSEAM-03, T-1207-06
    """
    mode_val = os.environ.get("GEOLENS_TENANCY_MODE", "").lower().strip()

    if mode_val != "multi_tenant":
        # Not requesting multi_tenant — single_tenant default or not set.
        return

    if loaded_extensions:
        # At least one overlay is registered; defer the RLS-layer assertion
        # to Phase 1208 where the full tenancy isolation gate is enforced.
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
