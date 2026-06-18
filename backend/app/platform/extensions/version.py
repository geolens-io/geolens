"""Extension API version contract for GeoLens overlay compatibility (OCG-04).

``EXTENSION_API_VERSION`` is an **integer** that increments whenever a Protocol
signature or registry contract changes in a way that requires overlay updates.

Bump convention
---------------
Bump this constant (and update overlay packages before re-releasing core) when:

- A required method is added to or removed from any Protocol in ``protocols.py``.
- A registry key is renamed or its expected type changes.
- The ``register_extensions(registry)`` calling convention changes.
- A single-slot vs. additive-slot classification changes for an existing key.

**Do NOT bump** for:
- New optional methods (Protocol evolution with default no-ops).
- New registry keys that overlays may optionally populate.
- Internal implementation changes with no contract impact.

Overlay declaration
-------------------
Each overlay **should** declare (recommended — opts the overlay into skew
detection)::

    from app.platform.extensions.version import EXTENSION_API_VERSION

as a module-level attribute in its ``register_extensions`` module (e.g. the
callable returned by the ``geolens.extensions`` entry point). The loader reads
this attribute via ``getattr(loader, "EXTENSION_API_VERSION", None)`` and calls
``check_extension_api_version()`` before invoking the overlay. An overlay that
does not declare a version is treated as legacy/version-0 and loads with a
WARNING (backward compatibility — see ``check_extension_api_version``); only a
declared-but-mismatched version is a hard failure.

References: OCG-04
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: First pinned version — increment when any Protocol or registry contract changes.
EXTENSION_API_VERSION: int = 1


def check_extension_api_version(name: str, declared_version: int | None) -> None:
    """Raise ``RuntimeError`` if ``declared_version`` is not compatible with core.

    Called by ``load_extensions()`` BEFORE invoking each overlay's
    ``register_extensions`` callback. A version mismatch is a hard error that
    escapes the broad-except in the loader — the operator must fix the overlay
    or pin the core to a compatible release before the service can boot.

    Parameters
    ----------
    name:
        The entry-point name of the overlay (used in the error message).
    declared_version:
        The value of ``EXTENSION_API_VERSION`` read from the overlay's loader
        callable. ``None`` means the overlay does not declare a version
        (legacy overlay — version-0 convention).

    Backward compatibility
    ----------------------
    An overlay that does **not** declare ``EXTENSION_API_VERSION`` (``None``) is
    treated as a legacy/version-0 overlay and is **allowed to load** with a
    WARNING — NOT a hard failure. This is deliberate open-core hygiene: the
    enterprise overlay is a separately-distributed package that predates this
    constant, so hard-failing on undeclared would brick every already-released
    overlay the moment a customer upgrades core. The skew protection OCG-04
    targets is the *declared-but-mismatched* case, which still raises. A future
    core MAY tighten this to require declaration once all shipped overlays
    declare a version.

    Raises
    ------
    RuntimeError
        Only when ``declared_version`` is a concrete integer that does not equal
        ``EXTENSION_API_VERSION`` (genuine version skew). Undeclared (``None``)
        does not raise.
    """
    if declared_version is None:
        logger.warning(
            "Overlay '%s' does not declare EXTENSION_API_VERSION; treating as "
            "legacy/version-0 and loading. Add `EXTENSION_API_VERSION = %d` to "
            "the overlay's register_extensions module to opt into skew detection. "
            "Core EXTENSION_API_VERSION=%d.",
            name,
            EXTENSION_API_VERSION,
            EXTENSION_API_VERSION,
        )
        return
    if declared_version != EXTENSION_API_VERSION:
        raise RuntimeError(
            f"Overlay '{name}' declares EXTENSION_API_VERSION={declared_version} "
            f"but core requires EXTENSION_API_VERSION={EXTENSION_API_VERSION}. "
            f"Update the overlay to match the core version or pin core to a compatible release."
        )
