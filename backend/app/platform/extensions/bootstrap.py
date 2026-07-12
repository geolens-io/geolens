"""Shared bootstrap helper for API lifespan and worker startup.

WORK-01: Extract ONE shared ``bootstrap()`` helper that performs the full
extension-load + edition-init + storage/cache-init sequence. Call it from
BOTH ``api/main.py`` lifespan AND ``worker.main()`` so the two entrypoints
cannot drift into different bootstrap states.

WORK-02: ``assert_enterprise_ports_resolved()`` performs an affirmative
post-bootstrap assertion: each overlay tier's single-slot ports MUST resolve to
a non-Default implementation (enterprise ports under a resolved enterprise
edition; cloud ports under ``GEOLENS_TENANCY_MODE=multi_tenant``) or the process
raises ``RuntimeError`` and refuses to start.

References: WORK-01, WORK-02
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

from app.core.edition import (
    EditionInfo,
    check_enterprise_overlay_requested,
    check_tenancy_mode_supported,
    get_edition,
    init_edition,
)
from app.core.tenancy import is_multi_tenant
from app.platform.extensions import (
    get_billing_extensions,
    get_extension_routers,
    list_extensions,
    load_extensions,
)
from app.platform.cache import init_cache
from app.platform.storage import init_storage

logger = structlog.stdlib.get_logger(__name__)

# ---------------------------------------------------------------------------
# Ports checked by assert_enterprise_ports_resolved() (WORK-02)
# ---------------------------------------------------------------------------

#: Single-slot ports the ENTERPRISE overlay registers (permission/identity/
#: workflow). Any port still matching its Default* class name under a resolved
#: enterprise edition is un-resolved and causes a loud failure.
_ENTERPRISE_PORT_CHECKS: list[tuple[str, str]] = [
    ("permission", "DefaultPermissionExtension"),
    ("identity", "DefaultIdentityExtension"),
    ("workflow", "DefaultWorkflowExtension"),
]

#: Single-slot ports that ONLY the cloud (multi-tenant) overlay registers.
#: WORK-02 fix: the enterprise overlay never registers processing_port /
#: catalog_port (it fills auth/identity/permission/workflow/audit/branding), so
#: a bare enterprise worker legitimately runs the community defaults for these.
#: Demanding them under GEOLENS_EDITION=enterprise crash-looped the worker while
#: the API served fine. They are required only when multi-tenant — the same
#: signal that already REQUIRES the cloud overlay (see check_tenancy_mode_supported).
#:
#: entitlement is included: DefaultEntitlementPort is fail-OPEN (grant-all
#: has_feature + no-op enforce_limit) and the cloud overlay replaces it for
#: per-tenant plan/quota enforcement (Phase 1213). Without it here, a
#: multi-tenant worker could boot green while every tenant quota check silently
#: passes.
_CLOUD_PORT_CHECKS: list[tuple[str, str]] = [
    ("processing_port", "DefaultProcessingPort"),
    ("catalog_port", "DefaultCatalogPort"),
    ("entitlement", "DefaultEntitlementPort"),
]

#: Additive-slot keys written into the `_extensions` registry by CORE bootstrap
#: (not by an enterprise overlay). These must NOT count toward the
#: overlay/edition-detection signal — otherwise simply wiring the core
#: notification port would make a community deployment mis-detect as
#: ``enterprise`` (Phase 1230). The filter is order- and repeat-bootstrap-safe:
#: even if the slot persists across bootstrap calls, edition stays community.
_CORE_BUILTIN_SLOT_KEYS: frozenset[str] = frozenset({"notification_sinks"})


def _overlay_extension_names() -> list[str]:
    """Registered extension names that signal an enterprise *overlay*.

    `list_extensions()` minus the core-builtin slot keys — the authoritative
    input for edition detection and the overlay-requested / tenancy guards.
    """
    return [n for n in list_extensions() if n not in _CORE_BUILTIN_SLOT_KEYS]


def assert_enterprise_ports_resolved() -> None:
    """Assert every REQUIRED single-slot port is NOT the Default* impl.

    WORK-02 — Called by the worker after ``bootstrap()`` completes. Which ports
    are required depends on the resolved deployment tier:

    * Resolved edition ``enterprise`` (whatever ``get_edition()`` resolves — a
      signed license, the legacy ``GEOLENS_EDITION`` env var, or legacy
      extension auto-detection; keying on the resolved edition rather than the
      raw env var means a license-key activation that omits the env var is
      still covered) requires the enterprise-overlay ports:
      permission, identity, workflow.
    * ``GEOLENS_TENANCY_MODE=multi_tenant`` (the cloud overlay) additionally
      requires processing_port and catalog_port. The enterprise overlay never
      registers those, so demanding them under bare enterprise crash-looped the
      worker while the API served fine — the WORK-02 regression this fixes.

    If any required port is still the Default impl, raises ``RuntimeError``
    naming every still-Default port and pointing at the build-time-bake remedy.
    Community with no cloud overlay: no-op (returns silently).

    Logs the resolved implementation class for every known port at INFO level
    regardless of tier — makes silent-community-fallback observable in
    production logs (WORK-02 observability clause).
    """
    from app.platform.extensions import (
        get_catalog_port,
        get_entitlement_port,
        get_identity_extension,
        get_permission_extension,
        get_processing_port,
        get_workflow_extension,
    )

    _port_getters = {
        "processing_port": get_processing_port,
        "catalog_port": get_catalog_port,
        "entitlement": get_entitlement_port,
        "permission": get_permission_extension,
        "identity": get_identity_extension,
        "workflow": get_workflow_extension,
    }

    # Resolve every known port once — for the observability log AND the assertion.
    resolved: dict[str, str] = {
        key: type(getter()).__name__ for key, getter in _port_getters.items()
    }
    for port_key, cls_name in resolved.items():
        logger.info("Extension port resolved", port=port_key, impl=cls_name)

    # Build the REQUIRED set from the resolved tier. Tenancy comes from the
    # settings-backed helper (not raw os.environ) so a multi_tenant value set
    # only in the repo .env file — not exported — is still honored, matching how
    # the rest of the app resolves tenancy.
    required: list[tuple[str, str]] = []
    if get_edition().edition == "enterprise":
        required += _ENTERPRISE_PORT_CHECKS
    if is_multi_tenant():
        required += _CLOUD_PORT_CHECKS

    if not required:
        # Community, single-tenant — no overlay ports are required.
        return

    still_default_keys = [
        port_key
        for port_key, default_cls_name in required
        if resolved[port_key] == default_cls_name
    ]

    if still_default_keys:
        still_list = ", ".join(f"{k} ({resolved[k]})" for k in still_default_keys)

        # Point at the overlay that actually provides each missing tier. The
        # enterprise overlay does NOT ship processing_port/catalog_port, so a
        # cloud-port failure must send the operator to the cloud overlay build,
        # not INSTALL_ENTERPRISE_OVERLAY=1 (which bakes /enterprise only).
        cloud_keys = {k for k, _ in _CLOUD_PORT_CHECKS}
        remedies: list[str] = []
        if any(k not in cloud_keys for k in still_default_keys):
            remedies.append(
                "the enterprise overlay (build --build-arg INSTALL_OVERLAYS="
                '"/enterprise", or the legacy --build-arg '
                "INSTALL_ENTERPRISE_OVERLAY=1)"
            )
        if any(k in cloud_keys for k in still_default_keys):
            remedies.append(
                "the cloud overlay that provides processing_port/catalog_port "
                "under GEOLENS_TENANCY_MODE=multi_tenant (build --build-arg "
                'INSTALL_OVERLAYS="/enterprise /cloud")'
            )

        raise RuntimeError(
            f"A licensed/overlay edition is active but the following single-slot "
            f"ports are still the Default community implementations: [{still_list}]. "
            f"Pre-bake {' and '.join(remedies)} into the image at build time "
            f"(see ARG INSTALL_OVERLAYS in the Dockerfile). References: WORK-02."
        )


def register_builtin_notification_sinks() -> None:
    """Register EnvConfiguredNotificationSink into the notification_sinks additive slot.

    This is the IN-01 carry-forward fix from the 1229 code review: without this
    call, notify() only fans out to DefaultNotificationSink (no-op) and every
    event silently drops. Calling this from the shared bootstrap() ensures the
    real sink is present in BOTH the API process (bootstrap(app=app)) and the
    procrastinate worker (bootstrap(app=None), worker.py:288) — closing the
    worker split-brain by construction.

    Registration contract:
    - Uses the setdefault+append pattern documented in extensions/__init__.py
      (same shape as audit_sinks and billing_extensions) to preserve any sinks
      already appended by enterprise overlays.
    - Idempotent: scans the existing slot for an EnvConfiguredNotificationSink
      instance and returns early if one is already present — safe to call more
      than once across test setups or process reloads.

    References: IN-01 (1229 review), NOTIF-01 (additive slot contract)
    """
    # Deferred import — Phase 214 discipline; avoids circular module-load at startup.
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultNotificationSink
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    # Acquire (or initialise) the additive slot without replacing existing entries.
    sinks = _extensions.setdefault("notification_sinks", [DefaultNotificationSink()])

    # Idempotency guard: do not append a second EnvConfiguredNotificationSink.
    if any(isinstance(s, EnvConfiguredNotificationSink) for s in sinks):
        return

    sinks.append(EnvConfiguredNotificationSink())
    logger.info(
        "Built-in notification sink registered",
        sink="EnvConfiguredNotificationSink",
    )


async def bootstrap(*, app: "FastAPI | None" = None) -> EditionInfo:
    """Shared bootstrap sequence for BOTH API lifespan and worker startup.

    Performs IN ORDER:

    1. ``load_extensions()`` — discover + register overlay extensions.
    2. ``check_enterprise_overlay_requested(list_extensions())`` — fail loud
       if GEOLENS_EDITION=enterprise but no overlay was loaded (BUG-003).
    3. ``init_edition(list_extensions())`` — resolve the edition singleton.
    4. Log the detected edition.
    5. If ``app`` is provided: include extension routers into the app
       (API mode only — the worker has no FastAPI app).
    6. ``init_storage()`` — register the storage provider (overlays that
       register storage providers must be loaded first, hence ordering).
    7. S3 connectivity/health probe (if ``settings.storage_provider == "s3"``).
    8. ``get_billing_extensions().on_startup(app)`` dispatch loop — only when
       ``app`` is provided (billing startup hooks need the app object).
    9. ``init_cache()`` — register the cache provider.

    Returns the ``EditionInfo`` from ``get_edition()``.

    Args:
        app: The FastAPI application instance (API mode). Pass ``None`` for
            worker mode — router include and billing dispatch are skipped.

    References: WORK-01
    """
    from app.core.config import settings

    # Step 1: Discover + load overlay extensions.
    load_extensions()

    # Step 2: Fail loud if enterprise is requested but overlay absent (BUG-003).
    # Edition-signal calls use _overlay_extension_names() so core builtins
    # (e.g. the notification sink) never read as an enterprise overlay (Phase 1230).
    check_enterprise_overlay_requested(_overlay_extension_names())

    # Step 2b: GUARD-01 edition-half — fail loud if multi_tenant is configured
    # but no tenancy-providing overlay is loaded (T-1207-06, Phase 1207-02).
    check_tenancy_mode_supported(_overlay_extension_names())

    # Step 3: Resolve the edition singleton from loaded OVERLAY extensions.
    init_edition(_overlay_extension_names())
    edition_info = get_edition()

    # Step 4: Log detected edition.
    logger.info(
        "Edition detected",
        edition=edition_info.edition,
        features=list(edition_info.features),
    )

    # Step 4b: Register the built-in notification sink AFTER edition resolution.
    # CRITICAL ordering (Phase 1230 edition-pollution fix): this writes into the
    # `notification_sinks` additive slot of the SAME `_extensions` registry that
    # `init_edition()` / `check_enterprise_overlay_requested()` read to detect the
    # edition. Registering the core sink BEFORE init_edition made `list_extensions()`
    # non-empty, so a plain community deployment mis-detected as `enterprise` (and
    # logged the "enterprise WITHOUT a verified license" warning). Doing it here keeps
    # edition detection driven purely by overlay-loaded extensions. Runs
    # unconditionally for both API (app=<FastAPI>) and worker (app=None) so the sink
    # is present in both processes — closing the worker split-brain by construction
    # (IN-01 carry-forward). Any overlay-registered sinks loaded in step 1 are
    # preserved (setdefault+append).
    register_builtin_notification_sinks()

    # Step 5 (API mode only): include extension routers into the app.
    if app is not None:
        for ext_router in get_extension_routers():
            app.include_router(ext_router)

    # Step 6: Initialize storage (after extensions so provider overlays register).
    init_storage()

    # Step 7: S3 connectivity / health probe.
    if settings.storage_provider == "s3":
        from app.platform.storage import get_storage

        storage = get_storage()
        try:
            await storage.health_check()
            import boto3 as _boto3

            _session = _boto3.Session()
            _creds = _session.get_credentials()
            cred_method = _creds.method if _creds else "unknown"
            if settings.s3_access_key_id:
                cred_method = "explicit-keys"
            logger.info(
                "S3 connectivity verified",
                bucket=settings.s3_bucket,
                credential_source=cred_method,
                addressing_style=settings.s3_addressing_style,
            )
        except Exception as exc:  # broad: S3/MinIO SDK can throw varied connection/auth/region errors; fail-fast on boot
            logger.exception(
                "S3 health check failed -- cannot start",
                error=str(exc),
                bucket=settings.s3_bucket,
                endpoint=settings.s3_endpoint,
                region=settings.s3_region,
            )
            raise RuntimeError(f"S3 health check failed: {exc}") from exc

    # Step 8 (API mode only): billing extension on_startup dispatch.
    # Community: DefaultBillingExtension.on_startup is a no-op.
    # Enterprise overlay registers MarketplaceBillingExtension (D-13).
    # asyncio.wait_for(timeout=10.0) caps each extension at 10s.
    # Per-extension try/except (D-12) isolates failures.
    if app is not None:
        for ext in get_billing_extensions():
            try:
                await asyncio.wait_for(ext.on_startup(app), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "BillingExtension.on_startup timed out -- continuing without billing",
                    extension=type(ext).__name__,
                    timeout_seconds=10.0,
                )
            except Exception as exc:  # broad: extension startup hooks can throw provider-specific errors; isolate per-extension
                logger.warning(
                    "BillingExtension.on_startup failed -- continuing without billing",
                    extension=type(ext).__name__,
                    error=str(exc),
                )

    # Step 9: Initialize cache.
    init_cache()

    # Step 10 (ISO-02): Mode-gated idempotent RLS enablement (Phase 1208-02).
    # In single_tenant: no-op (zero SQL, zero planner cost).
    # In multi_tenant: enables + FORCEs RLS on the 6 tenant-shared tables so
    # the FORCE RLS policies from 0006_tenant_rls become active.  Idempotent —
    # checks pg_class flags before issuing any ALTER TABLE, so multi-worker
    # concurrent boots do not contend on ACCESS EXCLUSIVE locks (T-1208-08).
    # A mode flip (setting GEOLENS_TENANCY_MODE=multi_tenant) needs no new
    # migration — this call enables the already-present policies at boot.
    from app.core.db.rls import apply_tenancy_rls_from_engine  # noqa: E402

    await apply_tenancy_rls_from_engine()

    return edition_info
