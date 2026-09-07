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
    DefaultAnthropicProvider,
    DefaultAuditSink,
    DefaultAuthExtension,
    DefaultBillingExtension,
    DefaultBrandingExtension,
    DefaultCatalogPort,
    DefaultConnectorExtension,
    DefaultDataServingExtension,
    DefaultEntitlementPort,
    DefaultIdentityExtension,
    DefaultNotificationSink,
    DefaultOpenAICompatibleProvider,
    DefaultOpenAIEmbeddingProvider,
    DefaultPermissionExtension,
    DefaultProcessingPort,
    DefaultWorkflowExtension,
)
from app.platform.extensions.protocols import (
    AuditSink,
    AuthExtension,
    BillingExtension,
    BrandingExtension,
    ConnectorCredentialRef as ConnectorCredentialRef,
    ConnectorDefinition as ConnectorDefinition,
    ConnectorResource as ConnectorResource,
    NotificationSink,
    # feat(#1068): runtime (not TYPE_CHECKING) re-exports — an overlay
    # implementing record_audience must CONSTRUCT a RecordAudience, so the
    # name has to resolve at run time.
    RecordAudience as RecordAudience,
    RecordAudienceQuery as RecordAudienceQuery,
)

if TYPE_CHECKING:
    from app.core.catalog_port import CatalogPort
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort
    from app.platform.extensions.protocols import (
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
# point iteration order is unspecified, so composition must never depend on
# the installer/filesystem order returned by importlib.metadata.
DEFAULT_EXTENSION_LOAD_PRIORITY = 100

#: Single-slot keys: exactly ONE overlay may claim each of these.
#: A second overlay writing the same key RAISES ExtensionSlotConflictError.
SINGLE_SLOT_KEYS: frozenset[str] = frozenset(
    {
        "permission",
        "identity",
        "processing_port",
        "catalog_port",
        "workflow",
        "branding",
        "auth",
        "entitlement",  # ENTSEAM-01 — cloud overlay claims this
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
        "notification_sinks",  # NOTIF-01 — overlays append sinks
        "_routers",
    }
)

#: Tracks which overlay name first claimed each single-slot key.
_slot_owners: dict[str, str] = {}


class ExtensionSlotConflictError(RuntimeError):
    """Raised when two overlays write the same single-slot key (SLOT-01)."""


def _run_loader_with_slot_guard(ep_name: str, loader: object, registry: dict) -> None:
    """Invoke ``loader(registry)`` and detect duplicate single-slot writes (SLOT-01).

    Raises :class:`ExtensionSlotConflictError` if a single-slot key changes
    owner. :data:`ADDITIVE_SLOT_KEYS` are exempt — they legitimately stack.
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
                # SLOT-02/CLOUD-04: a replacement is allowed only if it
                # transparently wraps the prior value via __slot_inner__;
                # a bare replacement or a wrong/missing inner still raises.
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

    Version contract (OCG-04): each loader must declare
    ``EXTENSION_API_VERSION`` matching
    :data:`app.platform.extensions.version.EXTENSION_API_VERSION`; a mismatch
    raises :class:`RuntimeError` and is never swallowed. Other loader
    exceptions (e.g. missing dependencies) are caught and logged as warnings.

    Slot-conflict guard (SLOT-01): a second overlay writing a non-additive
    single-slot key (see :data:`SINGLE_SLOT_KEYS`) raises
    :class:`ExtensionSlotConflictError`. :data:`ADDITIVE_SLOT_KEYS` are exempt.

    Wrap-don't-replace (SLOT-02/CLOUD-04): to add behavior on a single-slot
    key, read the prior impl via the matching ``get_*_extension()``, wrap it,
    set ``wrapper.__slot_inner__ = prior`` so the guard recognizes a
    transparent wrap, and register the wrapper under the same key LAST::

        prior = get_permission_extension()
        wrapper = TierAwarePermission(inner=prior)
        wrapper.__slot_inner__ = prior
        registry["permission"] = wrapper

    A wrapper whose ``__slot_inner__`` is not the exact prior instance is
    still rejected as a conflict.

    Deterministic composition order: a loader may declare an integer
    ``EXTENSION_LOAD_PRIORITY`` (default :data:`DEFAULT_EXTENSION_LOAD_PRIORITY`);
    lower loads first, ties broken by entry-point name. An overlay wrapping
    another overlay's single-slot port must declare a larger value.
    ``importlib.metadata`` entry-point iteration order is never authoritative.
    """
    global _loaded

    _routers.clear()
    _slot_owners.clear()

    discovered: list[tuple[int, str, object]] = []
    for ep in entry_points(group="geolens.extensions"):
        try:
            loader = ep.load()
            # OCG-04: version check runs before the loader call; its
            # RuntimeError escapes the broad except below.
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
    return name in _extensions


def list_extensions() -> list[str]:
    """Return the names of all registered extensions."""
    return list(_extensions.keys())


def get_extension_routers() -> list:
    """Return FastAPI routers registered by extensions."""
    return list(_routers)


# Typed accessors return the registered extension or a community default,
# so callers never see None instead of get_extension(...).


def get_branding_extension() -> BrandingExtension:
    """Return the registered BrandingExtension or the community default."""
    ext = _extensions.get("branding")
    if ext is None:
        return DefaultBrandingExtension()
    return ext  # type: ignore[return-value]


def get_auth_extension() -> AuthExtension:
    """Return the registered AuthExtension or the community default."""
    ext = _extensions.get("auth")
    if ext is None:
        return DefaultAuthExtension()
    return ext  # type: ignore[return-value]


def get_permission_extension() -> "PermissionExtension":
    """Return the registered PermissionExtension or the community default."""
    ext = _extensions.get("permission")
    if ext is None:
        return DefaultPermissionExtension()
    return ext  # type: ignore[return-value]


def get_workflow_extension() -> "WorkflowExtension":
    """Return the registered WorkflowExtension or the community default."""
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

    Community's ``DefaultIdentityExtension.resolve_identity_from_token``
    returns ``None``, leaving the existing JWT path unchanged.
    """
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]


def get_audit_sinks() -> list[AuditSink]:
    """Return all registered AuditSinks, or [DefaultAuditSink()] when unset.

    Additive slot: overlays append via
    ``registry.setdefault("audit_sinks", [DefaultAuditSink()]).append(sink)``.
    Reassigning the key drops DefaultAuditSink and breaks the AUDIT-05
    guarantee that every deployment writes at least one sink; this is not
    enforced beyond the architecture-guard test on direct ``log_action(`` calls.

    Returns a defensive copy so a sink can't mutate the registry mid-iteration.
    """
    sinks = _extensions.get("audit_sinks")
    if sinks is None:
        return [DefaultAuditSink()]
    return list(sinks)  # type: ignore[arg-type]


def get_billing_extensions() -> list[BillingExtension]:
    """Return registered BillingExtensions, or [DefaultBillingExtension()].

    Additive slot, list-shape like ``get_audit_sinks()``: overlays append via
    ``registry.setdefault("billing_extensions",
    [DefaultBillingExtension()]).append(ext)``. Reassigning the key drops
    DefaultBillingExtension — the lifespan dispatch loop tolerates this since
    the default is a no-op, but keep the setdefault+append convention anyway.

    Returns a defensive copy so an extension can't mutate the registry
    mid-iteration.
    """
    exts = _extensions.get("billing_extensions")
    if exts is None:
        return [DefaultBillingExtension()]
    return list(exts)  # type: ignore[arg-type]


def get_notification_sinks() -> list[NotificationSink]:
    """Return registered NotificationSinks, or [DefaultNotificationSink()].

    Additive slot, list-shape like ``get_audit_sinks()``: overlays append via
    ``registry.setdefault("notification_sinks",
    [DefaultNotificationSink()]).append(sink)``. Community (no notification
    env vars set) sends zero outbound notifications. Reassigning the key
    drops DefaultNotificationSink — use setdefault+append to preserve NOTIF-01.

    Returns a defensive copy so a sink can't mutate the registry mid-iteration.
    """
    sinks = _extensions.get("notification_sinks")
    if sinks is None:
        return [DefaultNotificationSink()]
    return list(sinks)  # type: ignore[arg-type]


def get_processing_port() -> "ProcessingPort":
    """Return the registered ProcessingPort or the community default.

    Single-slot, NOT list-shape like ``get_audit_sinks()`` — ProcessingPort
    is a singleton consumer surface; overlays REPLACE rather than append.

    ``DefaultProcessingPort`` forwards every call to the existing
    ``app.modules.catalog.*`` functions via deferred imports, so community
    behavior is unchanged.
    """
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]


def get_catalog_port() -> "CatalogPort":
    """Return the registered CatalogPort or the community default.

    Single-slot, symmetric partner to ``get_processing_port()``.
    """
    ext = _extensions.get("catalog_port")
    if ext is None:
        return DefaultCatalogPort()
    return ext  # type: ignore[return-value]


def get_entitlement_port() -> "EntitlementPort":
    """Return the registered EntitlementPort or the community grant-all default.

    Community and Enterprise both return ``DefaultEntitlementPort``
    (grant-all, fail-open) — correct because OSS/Enterprise aren't
    multi-tenant-tiered; real enforcement is the cloud overlay's job. The
    grant-all default never weakens ``require_enterprise()`` (edition gate)
    or ``PermissionExtension`` (RBAC) — the three seams are orthogonal.
    """
    ext = _extensions.get("entitlement")
    if ext is None:
        return DefaultEntitlementPort()
    return ext  # type: ignore[return-value]


def get_ai_provider(name: str) -> "AIProviderExtension":
    """Return the named AIProviderExtension or raise ValueError.

    ``_extensions["ai_providers"]`` is a ``dict[str, AIProviderExtension]``,
    distinct from the list-shape ``audit_sinks``/``billing_extensions`` and
    the single-slot ``processing_port``/``identity`` — AI dispatch fans out
    by name at request time (``LLM_PROVIDER`` config selects the key).

    Per-key ``setdefault`` seeds the two community defaults without
    overwriting an overlay that registered the same key before the first
    ``get_ai_provider()`` call; a new overlay-registered name coexists
    alongside the defaults.

    Raises ``ValueError("Unknown LLM provider: {name}")`` for unknown names,
    preserving the exception type/message existing callers catch.
    """
    providers = _extensions.setdefault("ai_providers", {})
    providers.setdefault("anthropic", DefaultAnthropicProvider())
    providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
    if name not in providers:
        raise ValueError(f"Unknown LLM provider: {name}")
    return providers[name]  # type: ignore[return-value]


def get_embedding_provider(name: str) -> "EmbeddingProviderExtension":
    """Return the named EmbeddingProviderExtension or raise ValueError.

    ``_extensions["embedding_providers"]`` is dict-shape like
    ``ai_providers``, but a separate registry — the same name
    (``"openai_compatible"``) can exist independently in both, since
    dispatch tables are name-scoped per extension type.

    Per-key ``setdefault`` seeds the community default without overwriting
    an overlay that registered the same key before the first
    ``get_embedding_provider()`` call.

    Raises ``ValueError("Unknown embedding provider: {name}")`` for unknown
    names, symmetric with ``get_ai_provider``.
    """
    providers = _extensions.setdefault("embedding_providers", {})
    providers.setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())
    if name not in providers:
        raise ValueError(f"Unknown embedding provider: {name}")
    return providers[name]  # type: ignore[return-value]
