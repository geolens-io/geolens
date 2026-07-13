"""Extension registry for GeoLens enterprise extensions.

Discovers and loads extensions via the ``geolens.extensions`` entry-point
group. Community edition runs with an empty registry; enterprise packages
register themselves by providing entry points that populate the registry dict.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import structlog

from app.platform.extensions.version import check_extension_api_version
from app.platform.extensions.defaults import (
    DefaultAnthropicProvider,  # NEW (Phase 226)
    DefaultAuditExtension,
    DefaultAuditSink,  # NEW (Phase 222)
    DefaultAuthExtension,
    DefaultBillingExtension,  # NEW (Phase 223)
    DefaultBrandingExtension,
    DefaultCatalogPort,  # NEW (Phase 230)
    DefaultConnectorExtension,
    DefaultDataServingExtension,
    DefaultEntitlementPort,  # NEW (Phase 1207)
    DefaultIdentityExtension,
    DefaultNotificationSink,  # NEW (Phase 1229)
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
    ConnectorCredentialRef as ConnectorCredentialRef,
    ConnectorDefinition as ConnectorDefinition,
    ConnectorResource as ConnectorResource,
    NotificationSink,  # NEW (Phase 1229)
)

if TYPE_CHECKING:
    from app.core.catalog_port import CatalogPort  # NEW (Phase 230)
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort  # NEW (Phase 225)
    from app.platform.extensions.protocols import (  # NEW (Phase 226 + 231 + 1207)
        AIProviderExtension,
        ConnectorExtension,
        DataServingExtension,
        EmbeddingProviderExtension,
        EntitlementPort,
        PermissionExtension,
        WorkflowExtension,
    )

logger = structlog.stdlib.get_logger(__name__)

_extensions: dict[str, object] = {}
_routers: list = []
_loaded: bool = False

# Foundational overlays register first; wrappers choose a larger value. Entry
# point iteration order is explicitly unspecified, so composition must never
# depend on the installer/filesystem order returned by importlib.metadata.
DEFAULT_EXTENSION_LOAD_PRIORITY = 100

# ---------------------------------------------------------------------------
# Slot classification (SLOT-01)
# ---------------------------------------------------------------------------

#: Single-slot keys: exactly ONE overlay may claim each of these.
#: A second different overlay writing the same key RAISES ExtensionSlotConflictError.
SINGLE_SLOT_KEYS: frozenset[str] = frozenset(
    {
        "permission",
        "identity",
        "processing_port",
        "catalog_port",
        "workflow",
        "branding",
        "audit",
        "auth",
        "entitlement",  # NEW (Phase 1207 / ENTSEAM-01) — cloud overlay claims this in Phase 1213
        "connectors",
        "data_serving",
    }
)

#: Additive-slot keys: multiple overlays may write/append to these concurrently.
#: Exempt from the slot-conflict guard by design.
ADDITIVE_SLOT_KEYS: frozenset[str] = frozenset(
    {
        "audit_sinks",
        "billing_extensions",
        "ai_providers",
        "embedding_providers",
        "notification_sinks",  # NEW (Phase 1229 NOTIF-01) — overlays append sinks
        "_routers",
    }
)

#: Tracks which overlay name first claimed each single-slot key.
_slot_owners: dict[str, str] = {}


class ExtensionSlotConflictError(RuntimeError):
    """Raised when two overlays attempt to write the same non-additive single-slot key.

    References: SLOT-01
    """


def _run_loader_with_slot_guard(ep_name: str, loader: object, registry: dict) -> None:
    """Invoke ``loader(registry)`` and detect duplicate single-slot writes (SLOT-01).

    Before the loader runs, snapshot which single-slot keys are already occupied.
    After the loader runs, check each single-slot key: if it was previously owned
    by a DIFFERENT overlay, raise :class:`ExtensionSlotConflictError` naming the
    key and both provider classes.

    Additive keys (see :data:`ADDITIVE_SLOT_KEYS`) are exempt — they legitimately
    stack across overlays.
    """
    # Snapshot the single-slot keys already present (and who owns them)
    pre_snapshot: dict[str, object] = {
        k: registry[k] for k in SINGLE_SLOT_KEYS if k in registry
    }

    loader(registry)  # type: ignore[call-arg]

    # Detect conflicts: a key that existed BEFORE and was replaced by a DIFFERENT object
    for key in SINGLE_SLOT_KEYS:
        if key not in registry:
            continue
        new_val = registry[key]
        if key in pre_snapshot:
            prior_val = pre_snapshot[key]
            if new_val is not prior_val:
                # Check the sanctioned wrap path (SLOT-02 / CLOUD-04):
                # A replacement is allowed IFF the new value transparently carries
                # the prior value as a marked inner via __slot_inner__.
                # This lets a second overlay compose-wrap the first overlay's port
                # without clobbering it.  A bare replacement (no __slot_inner__, or
                # __slot_inner__ pointing to a different object) still raises.
                if getattr(new_val, "__slot_inner__", None) is prior_val:
                    # Sanctioned wrap — update ownership to reflect the chain.
                    _slot_owners[key] = ep_name
                    continue
                # Bare replace or misdirected inner — conflict.
                prior_owner = _slot_owners.get(key, "unknown")
                raise ExtensionSlotConflictError(
                    f"Extension slot conflict on key '{key}': "
                    f"overlay '{ep_name}' ({type(new_val).__name__}) "
                    f"attempted to replace the existing registration by "
                    f"overlay '{prior_owner}' ({type(prior_val).__name__}). "
                    f"Overlays needing additive behavior MUST wrap the prior impl "
                    f"via the corresponding get_*_extension() accessor at construction "
                    f"time and register last — never bare re-register a single-slot key. "
                    f"Use `wrapper.__slot_inner__ = <prior_impl>` to mark a sanctioned "
                    f"wrap (SLOT-02 contract). References: SLOT-01, SLOT-02."
                )
        else:
            # First claim — record ownership
            _slot_owners[key] = ep_name


def load_extensions() -> None:
    """Discover and load all extensions from the ``geolens.extensions`` group.

    Version contract (OCG-04)
    -------------------------
    Each overlay's loader callable MUST declare ``EXTENSION_API_VERSION`` equal
    to core's :data:`app.platform.extensions.version.EXTENSION_API_VERSION`.
    A version mismatch raises :class:`RuntimeError` and is NOT swallowed — the
    operator must align the overlay and core versions before the service boots.
    Only non-version loader exceptions (e.g., missing dependencies) are caught
    and logged as warnings.

    Slot-conflict guard (SLOT-01)
    -----------------------------
    Duplicate writes to non-additive single-slot keys (see :data:`SINGLE_SLOT_KEYS`)
    raise :class:`ExtensionSlotConflictError` naming the key and both providers.
    Additive slots (see :data:`ADDITIVE_SLOT_KEYS`) are exempt.

    Wrap-don't-replace rule (SLOT-02)
    ----------------------------------
    An overlay that needs additive behavior on a single-slot key MUST wrap the
    prior implementation retrieved via the corresponding ``get_*_extension()``
    accessor at construction time, then register the wrapping impl under the
    same key LAST — never bare re-register the key (the guard rejects that as a
    conflict).

    The wrapper MUST set ``__slot_inner__ = <prior_impl>`` (the exact object
    returned by ``get_*_extension()`` at wrapper construction time) so the guard
    can verify the wrap is transparent and not a clobber.  Example::

        class TierAwarePermission:
            def __init__(self, inner) -> None:
                self.__slot_inner__ = inner   # REQUIRED: marks the sanctioned wrap
                self._inner = inner

            async def check_permission(self, *args, **kwargs):
                return await self._inner.check_permission(*args, **kwargs)

        def register_extensions(registry):
            prior = get_permission_extension()  # read BEFORE writing
            wrapper = TierAwarePermission(inner=prior)
            registry["permission"] = wrapper    # guard allows: __slot_inner__ is prior

    A wrapper whose ``__slot_inner__`` does NOT point to the exact prior instance
    (e.g. points to ``None`` or an unrelated object) is still rejected as a
    conflict.

    References: SLOT-02, CLOUD-04

    Deterministic composition order
    -------------------------------
    A loader may declare an integer ``EXTENSION_LOAD_PRIORITY`` attribute.
    Lower values load first; ties are ordered by entry-point name. Loaders that
    omit it use :data:`DEFAULT_EXTENSION_LOAD_PRIORITY`. An overlay that wraps
    another overlay's single-slot ports must therefore declare a larger value.
    ``importlib.metadata`` entry-point iteration order is never authoritative.
    """
    global _loaded

    _routers.clear()
    _slot_owners.clear()

    discovered: list[tuple[int, str, object]] = []
    for ep in entry_points(group="geolens.extensions"):
        try:
            loader = ep.load()
            # OCG-04: check declared overlay API version BEFORE invoking the loader.
            # RuntimeError from check_extension_api_version escapes the broad-except below.
            declared_version = getattr(loader, "EXTENSION_API_VERSION", None)
            check_extension_api_version(ep.name, declared_version)
            if not callable(loader):
                logger.warning("Extension entry point is not callable", name=ep.name)
                continue

            try:
                loader_namespace = vars(loader)
            except TypeError:
                loader_namespace = {}
            priority = loader_namespace.get(
                "EXTENSION_LOAD_PRIORITY", DEFAULT_EXTENSION_LOAD_PRIORITY
            )
            if type(priority) is not int:
                raise RuntimeError(
                    f"Extension '{ep.name}' declares invalid "
                    f"EXTENSION_LOAD_PRIORITY={priority!r}; expected an integer"
                )
            discovered.append((priority, ep.name, loader))
        except RuntimeError:
            # Version-mismatch and slot-conflict errors must propagate loudly.
            raise
        except Exception:  # broad: extension entry-point loaders may raise provider-specific errors; logged via logger.warning
            logger.warning("Failed to load extension", name=ep.name, exc_info=True)

    for priority, ep_name, loader in sorted(
        discovered, key=lambda item: (item[0], item[1])
    ):
        try:
            _run_loader_with_slot_guard(ep_name, loader, _extensions)
            logger.info("Loaded extension", name=ep_name, priority=priority)
        except RuntimeError:
            raise
        except Exception:  # broad: extension loaders may raise provider-specific errors; logged via logger.warning
            logger.warning("Failed to load extension", name=ep_name, exc_info=True)

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


def get_data_serving_extension() -> "DataServingExtension":
    """Return provider-neutral serving hooks or the Community no-op default."""
    ext = _extensions.get("data_serving")
    if ext is None:
        return DefaultDataServingExtension()
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


def get_notification_sinks() -> list[NotificationSink]:
    """Return all registered NotificationSinks, or [DefaultNotificationSink()] when slot missing.

    Phase 1229 NOTIF-01 / NOTIF-04 — mirrors ``get_audit_sinks()`` and
    ``get_billing_extensions()`` shape exactly (list-shape, lazy default,
    defensive copy). The list shape is forward-compatible: a future overlay may
    register multiple channel sinks (SMTP + webhook + Slack incoming-webhook)
    alongside the community no-op.

    Community edition (no notification env vars set) gets
    ``[DefaultNotificationSink()]`` — behavior is byte-identical to today,
    zero outbound send, zero side effects.

    Enterprise overlays append to ``_extensions["notification_sinks"]`` via
    ``setdefault + append`` in their ``register_extensions(registry)`` callback::

        sinks = registry.setdefault("notification_sinks", [DefaultNotificationSink()])
        sinks.append(SMTPNotificationSink(config))

    Reassigning the slot (``registry["notification_sinks"] = [MySink()]``) makes
    DefaultNotificationSink disappear from the iteration — use setdefault+append
    to preserve the additive contract (NOTIF-01).

    Returns a defensive ``list(sinks)`` copy so a sink cannot accidentally mutate
    the registry mid-iteration in ``notify()``.
    """
    sinks = _extensions.get("notification_sinks")
    if sinks is None:
        return [DefaultNotificationSink()]
    return list(sinks)  # type: ignore[arg-type]


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


def get_entitlement_port() -> "EntitlementPort":
    """Return the registered EntitlementPort or the community grant-all default.

    Phase 1207 / ENTSEAM-01 — single-slot shape mirroring get_permission_extension(),
    get_workflow_extension(), get_processing_port(), and get_catalog_port().

    Community and Enterprise both return ``DefaultEntitlementPort`` (grant-all,
    fail-OPEN) — correct because OSS/Enterprise are not multi-tenant-tiered; real
    enforcement is the cloud overlay's job (Phase 1213). The grant-all default never
    weakens ``require_enterprise()`` (edition gate) or ``PermissionExtension`` (RBAC)
    because all three seams are orthogonal.

    The cloud overlay (Phase 1213) registers a real implementation under
    ``"entitlement"`` in its ``register_extensions(registry)`` callback. The
    ExtensionSlotConflictError guard prevents two overlays from claiming the slot.
    """
    ext = _extensions.get("entitlement")
    if ext is None:
        return DefaultEntitlementPort()
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
