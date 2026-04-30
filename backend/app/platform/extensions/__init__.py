"""Extension registry for GeoLens enterprise extensions.

Discovers and loads extensions via the ``geolens.extensions`` entry-point
group. Community edition runs with an empty registry; enterprise packages
register themselves by providing entry points that populate the registry dict.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import structlog

from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuditSink,  # NEW (Phase 222)
    DefaultAuthExtension,
    DefaultBillingExtension,  # NEW (Phase 223)
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuditSink,  # NEW (Phase 222)
    AuthExtension,
    BillingExtension,  # NEW (Phase 223)
    BrandingExtension,
)

if TYPE_CHECKING:
    from app.core.identity import IdentityExtension

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


# ---------------------------------------------------------------------------
# Typed accessors — return the registered extension or a community default.
# Call sites use these instead of get_extension(...) so the protocol contract
# is always satisfied (community can never be `None`).
# ---------------------------------------------------------------------------


def get_branding_extension() -> BrandingExtension:
    """Return the registered BrandingExtension or the community default."""
    ext = _extensions.get("branding")
    if ext is None:
        return DefaultBrandingExtension()
    return ext  # type: ignore[return-value]


def get_audit_extension() -> AuditExtension:
    """Return the registered AuditExtension or the community default."""
    ext = _extensions.get("audit")
    if ext is None:
        return DefaultAuditExtension()
    return ext  # type: ignore[return-value]


def get_auth_extension() -> AuthExtension:
    """Return the registered AuthExtension or the community default."""
    ext = _extensions.get("auth")
    if ext is None:
        return DefaultAuthExtension()
    return ext  # type: ignore[return-value]


def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension or the community default.

    Phase 214 / IDENT-03 — mirrors ``get_branding_extension()``,
    ``get_audit_extension()``, and ``get_auth_extension()`` exactly.
    Enterprise overlays register an implementation under the ``"identity"``
    key via the ``geolens.extensions`` entry-point group; community
    edition gets the no-op ``DefaultIdentityExtension`` whose
    ``resolve_identity_from_token`` returns ``None`` (existing JWT
    path runs unchanged).
    """
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]


def get_audit_sinks() -> list[AuditSink]:
    """Return all registered AuditSinks, or [DefaultAuditSink()] when slot missing.

    Phase 222 D-09 / D-10 / D-11 — departure from the four existing
    single-instance accessors: returns a list (community always has 1 sink,
    enterprise can have N).

    Enterprise overlays append to ``_extensions["audit_sinks"]`` via
    ``setdefault + append`` in their ``register_extensions(registry)`` callback::

        sinks = registry.setdefault("audit_sinks", [DefaultAuditSink()])
        sinks.append(MyEnterpriseSink())

    Reassigning the slot (``registry["audit_sinks"] = [MySink()]``) makes
    DefaultAuditSink disappear and breaks AUDIT-05 row-write contract for
    that deployment. Phase 222 cannot enforce this in the contract (overlay
    code lives outside this repo); the architecture-guard test only catches
    direct ``log_action(`` calls, not registry misuse. Documented as Pitfall D
    in 222-RESEARCH.md.

    Returns a defensive ``list(sinks)`` copy so a sink cannot accidentally
    mutate the registry mid-iteration in ``audit_emit()``.
    """
    sinks = _extensions.get("audit_sinks")
    if sinks is None:
        return [DefaultAuditSink()]
    return list(sinks)  # type: ignore[arg-type]


def get_billing_extensions() -> list[BillingExtension]:
    """Return all registered BillingExtensions, or [DefaultBillingExtension()] when slot missing.

    Phase 223 D-06 — mirrors ``get_audit_sinks()`` shape verbatim (list-shape,
    lazy default, defensive copy). The list shape is forward-compatible: a
    future overlay may register a billing-event sink alongside a primary biller
    (e.g., audit-trail-style billing events). Cost of list shape over single-slot
    is one extra ``[]`` of syntax; benefit is symmetry with ``AuditSink`` (one
    pattern, not two).

    Enterprise overlays append to ``_extensions["billing_extensions"]`` via
    ``setdefault + append`` in their ``register_extensions(registry)`` callback::

        billing_extensions = registry.setdefault(
            "billing_extensions", [DefaultBillingExtension()]
        )
        billing_extensions.append(MarketplaceBillingExtension())

    Reassigning the slot (``registry["billing_extensions"] = [MyExt()]``) makes
    DefaultBillingExtension disappear from the iteration. The dispatch loop
    (api/main.py lifespan, Plan 02) tolerates this — DefaultBillingExtension
    is a no-op so its absence has no behavioral effect — but the
    ``setdefault + append`` discipline matches Phase 222's pattern and keeps
    the codebase consistent.

    Returns a defensive ``list(exts)`` copy so an extension cannot accidentally
    mutate the registry mid-iteration in the lifespan dispatch.
    """
    exts = _extensions.get("billing_extensions")
    if exts is None:
        return [DefaultBillingExtension()]
    return list(exts)  # type: ignore[arg-type]
