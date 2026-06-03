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
    DefaultAnthropicProvider,  # NEW (Phase 226)
    DefaultAuditExtension,
    DefaultAuditSink,  # NEW (Phase 222)
    DefaultAuthExtension,
    DefaultBillingExtension,  # NEW (Phase 223)
    DefaultBrandingExtension,
    DefaultCatalogPort,  # NEW (Phase 230)
    DefaultConnectorExtension,
    DefaultIdentityExtension,
    DefaultOpenAICompatibleProvider,  # NEW (Phase 226)
    DefaultOpenAIEmbeddingProvider,  # NEW (Phase 231)
    DefaultPermissionExtension,  # NEW (Phase 232)
    DefaultProcessingPort,  # NEW (Phase 225)
    DefaultWorkflowExtension,  # NEW (Phase 233)
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuditSink,  # NEW (Phase 222)
    AuthExtension,
    BillingExtension,  # NEW (Phase 223)
    BrandingExtension,
)

if TYPE_CHECKING:
    from app.core.catalog_port import CatalogPort  # NEW (Phase 230)
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort  # NEW (Phase 225)
    from app.platform.extensions.protocols import (  # NEW (Phase 226 + 231)
        AIProviderExtension,
        ConnectorExtension,
        EmbeddingProviderExtension,
        PermissionExtension,
        WorkflowExtension,
    )

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
        except Exception:  # broad: extension entry-point loaders may raise provider-specific errors; logged via logger.warning
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


def get_permission_extension() -> "PermissionExtension":
    """Return the registered PermissionExtension or the community default.

    Phase 232 / PERM-01 follows the single-slot extension shape used by
    identity, processing_port, and catalog_port. Permission policy is a single
    authority; overlays that need additive behavior can wrap
    DefaultPermissionExtension explicitly.
    """
    ext = _extensions.get("permission")
    if ext is None:
        return DefaultPermissionExtension()
    return ext  # type: ignore[return-value]


def get_workflow_extension() -> "WorkflowExtension":
    """Return the registered WorkflowExtension or the community default.

    Phase 233 / WORK-01 follows the same single-slot shape as PermissionExtension.
    Workflow policy is a singleton authority; overlays that need additive
    behavior can wrap DefaultWorkflowExtension explicitly.
    """
    ext = _extensions.get("workflow")
    if ext is None:
        return DefaultWorkflowExtension()
    return ext  # type: ignore[return-value]


def get_connector_extension() -> "ConnectorExtension":
    """Return the registered ConnectorExtension or the community default."""
    ext = _extensions.get("connectors")
    if ext is None:
        return DefaultConnectorExtension()
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


def get_processing_port() -> "ProcessingPort":
    """Return the registered ProcessingPort or the community default.

    Phase 225 / PROCESS-01 — single-slot shape (D-12), NOT list-shape
    like get_audit_sinks() / get_billing_extensions(). ProcessingPort is
    a singleton consumer surface; overlays REPLACE rather than append.

    Enterprise overlays register a tier-aware / quota-enforcing wrapper
    under the ``"processing_port"`` key via the ``geolens.extensions``
    entry-point group::

        registry["processing_port"] = TierAwareProcessingPort(quota_config)

    Community edition gets DefaultProcessingPort which forwards every
    call to the existing app.modules.catalog.* functions via deferred
    imports (D-09 / D-11 — behavior is byte-for-byte identical to
    pre-Phase-225).
    """
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]


def get_catalog_port() -> "CatalogPort":
    """Return the registered CatalogPort or the community default.

    Phase 230 / CATPORT-01 — symmetric partner to get_processing_port().
    CatalogPort is single-slot because it is a singleton boundary surface;
    overlays replace it under the "catalog_port" registry key.
    """
    ext = _extensions.get("catalog_port")
    if ext is None:
        return DefaultCatalogPort()
    return ext  # type: ignore[return-value]


def get_ai_provider(name: str) -> "AIProviderExtension":
    """Return the named AIProviderExtension or raise ValueError (Phase 226 D-04/D-05).

    Registry slot ``_extensions["ai_providers"]`` is a
    ``dict[str, AIProviderExtension]`` — NEW shape (D-04). Distinct from
    ``audit_sinks`` / ``billing_extensions`` (list-shape, iterated) and
    ``processing_port`` / ``identity`` (single-slot, replaced) because AI
    dispatch fans out by NAME at request time: ``LLM_PROVIDER`` PersistentConfig
    stores ``"anthropic"`` or ``"openai_compatible"`` (or any overlay-registered
    name like ``"bedrock"``), and the accessor returns THE provider matching that
    name. O(1) lookup; mirrors the audit's "dispatch table" wording verbatim.

    Per-key ``setdefault`` seeds the two community defaults without overwriting
    overlay registrations (D-05). If an overlay registered
    ``providers["anthropic"] = TierAwareAnthropicProvider()`` BEFORE the first
    ``get_ai_provider()`` call (during ``load_extensions()``), the seeding step
    skips that key and the overlay wins. If an overlay registers a NEW name
    ``providers["bedrock"] = BedrockProvider()``, both defaults plus the new
    provider coexist. Order-safe regardless of overlay registration timing —
    same shape as Phase 222's ``setdefault + append`` for list-shape, adapted
    to dict-shape.

    Raises ``ValueError("Unknown LLM provider: {name}")`` for unknown names
    (D-06 — preserves today's ``llm_loop.py:149`` exception type/message so
    existing tests that catch ValueError continue to pass).
    """
    providers = _extensions.setdefault("ai_providers", {})
    providers.setdefault("anthropic", DefaultAnthropicProvider())
    providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
    if name not in providers:
        raise ValueError(f"Unknown LLM provider: {name}")
    return providers[name]  # type: ignore[return-value]


def get_embedding_provider(name: str) -> "EmbeddingProviderExtension":
    """Return the named EmbeddingProviderExtension or raise ValueError (Phase 231 D-09/D-10).

    Registry slot ``_extensions["embedding_providers"]`` is a
    ``dict[str, EmbeddingProviderExtension]`` — same dict-shape as
    ``ai_providers`` (Phase 226 D-04). Distinct registry from ``ai_providers``;
    the same name (``"openai_compatible"``) coexists in both because dispatch
    tables are name-scoped per extension type (D-07).

    Per-key ``setdefault`` seeds the single community default without overwriting
    overlay registrations (D-10 mirroring Phase 226 D-05). If an overlay
    registered ``providers["openai_compatible"] = TierAwareEmbeddingProvider()``
    BEFORE the first ``get_embedding_provider()`` call, the seeding step skips
    that key and the overlay wins. If an overlay registers a NEW name
    ``providers["bedrock"] = BedrockEmbeddingProvider()``, both default and
    overlay coexist. Order-safe regardless of overlay registration timing.

    Raises ``ValueError("Unknown embedding provider: {name}")`` for unknown
    names (D-11 — symmetry with ``get_ai_provider``'s "Unknown LLM provider").
    """
    providers = _extensions.setdefault("embedding_providers", {})
    providers.setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())
    if name not in providers:
        raise ValueError(f"Unknown embedding provider: {name}")
    return providers[name]  # type: ignore[return-value]
