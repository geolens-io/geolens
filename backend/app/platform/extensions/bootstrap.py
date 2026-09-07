"""Shared bootstrap helper for API lifespan and worker startup.

WORK-01: ``bootstrap()`` is the ONE shared extension-load + edition-init +
storage/cache-init sequence, called from both ``api/main.py`` lifespan and
``worker.main()`` so the two entrypoints cannot drift into different states.

WORK-02: ``assert_enterprise_ports_resolved()`` asserts, post-bootstrap, that
each overlay tier's single-slot ports resolved to a non-Default impl
(enterprise ports under a resolved enterprise edition; cloud ports under
``GEOLENS_TENANCY_MODE=multi_tenant``) — else it raises ``RuntimeError`` and
the process refuses to start.
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
from app.platform.cache.provider import init_tile_cache
from app.platform.storage import init_storage

logger = structlog.stdlib.get_logger(__name__)

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
#: catalog_port, so a bare enterprise worker legitimately runs the community
#: defaults for these — demanding them under GEOLENS_EDITION=enterprise
#: crash-looped the worker while the API served fine. Required only when
#: multi-tenant, the same signal that already requires the cloud overlay.
#:
#: entitlement is included because DefaultEntitlementPort is fail-OPEN
#: (grant-all); without this check a multi-tenant worker could boot green
#: while every tenant quota check silently passes. data_serving is included
#: for the same fail-closed reason (Community default silently disables
#: cold-tier prep and tenant tile fairness).
_CLOUD_PORT_CHECKS: list[tuple[str, str]] = [
    ("processing_port", "DefaultProcessingPort"),
    ("catalog_port", "DefaultCatalogPort"),
    ("entitlement", "DefaultEntitlementPort"),
    ("data_serving", "DefaultDataServingExtension"),
]

#: Additive-slot keys written into the `_extensions` registry by CORE bootstrap
#: (not by an enterprise overlay). These must NOT count toward the
#: overlay/edition-detection signal — otherwise wiring the core notification
#: port would make a community deployment mis-detect as ``enterprise``.
_CORE_BUILTIN_SLOT_KEYS: frozenset[str] = frozenset({"notification_sinks"})


def _overlay_extension_names() -> list[str]:
    """``list_extensions()`` minus the core-builtin slot keys.

    The authoritative input for edition detection and the
    overlay-requested / tenancy guards.
    """
    return [n for n in list_extensions() if n not in _CORE_BUILTIN_SLOT_KEYS]


def assert_enterprise_ports_resolved() -> None:
    """Assert every REQUIRED single-slot port is NOT the Default* impl.

    Called by the worker after ``bootstrap()`` completes. Required ports
    depend on the resolved deployment tier:

    * Resolved edition ``enterprise`` (keyed on ``get_edition()``, not the raw
      env var, so a license-key activation that omits the env var is still
      covered) requires the enterprise-overlay ports: permission, identity,
      workflow.
    * ``GEOLENS_TENANCY_MODE=multi_tenant`` additionally requires
      processing_port, catalog_port, entitlement, and data_serving — ports
      the enterprise overlay never registers (WORK-02: demanding them under
      bare enterprise crash-looped the worker while the API served fine).

    If any required port is still the Default impl, raises ``RuntimeError``
    naming every still-Default port and pointing at the build-time-bake
    remedy. Community with no cloud overlay is a no-op.

    Logs the resolved implementation class for every known port at INFO
    level regardless of tier, so a silent community fallback is observable.
    """
    from app.platform.extensions import (
        get_catalog_port,
        get_data_serving_extension,
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
        "data_serving": get_data_serving_extension,
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

    # Tenancy comes from the settings-backed helper (not raw os.environ) so a
    # multi_tenant value set only in .env — not exported — is still honored.
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

        # Enterprise doesn't ship processing_port/catalog_port, so a
        # cloud-port failure must point the operator at the cloud image build.
        cloud_keys = {k for k, _ in _CLOUD_PORT_CHECKS}
        remedies: list[str] = []
        if any(k not in cloud_keys for k in still_default_keys):
            remedies.append("the enterprise overlay's immutable image")
        if any(k in cloud_keys for k in still_default_keys):
            remedies.append(
                "the cloud overlay image that provides processing_port/"
                "catalog_port/entitlement/data_serving under "
                "GEOLENS_TENANCY_MODE=multi_tenant"
            )

        raise RuntimeError(
            f"A licensed/overlay edition is active but the following single-slot "
            f"ports are still the Default community implementations: [{still_list}]. "
            f"Use {' and '.join(remedies)}. References: WORK-02."
        )


def register_builtin_notification_sinks() -> None:
    """Register EnvConfiguredNotificationSink into the notification_sinks slot.

    IN-01: without this call, notify() only fans out to DefaultNotificationSink
    (no-op) and every event silently drops. Calling this from the shared
    bootstrap() ensures the real sink is present in both the API process and
    the worker, closing a split-brain by construction.

    Uses setdefault+append (NOTIF-01) to preserve sinks an overlay already
    appended, and is idempotent — it returns early if an
    EnvConfiguredNotificationSink is already in the slot.
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

    Performs IN ORDER: load extensions; fail loud if GEOLENS_EDITION=enterprise
    but no overlay loaded (BUG-003); resolve + log the edition; include
    extension routers (API mode only); init storage (after extensions, so
    overlay storage providers register first); S3 health probe; billing
    extensions' ``on_startup(app)`` dispatch (API mode only); init cache;
    init the binary tile cache (in-memory fallback is API-only, fix(#1315)).

    Returns the ``EditionInfo`` from ``get_edition()``.

    Args:
        app: The FastAPI application instance (API mode). Pass ``None`` for
            worker mode — router include and billing dispatch are skipped.
    """
    from app.core.config import settings

    # Step 1: Discover + load overlay extensions.
    load_extensions()

    # Step 2 (BUG-003): fail loud if enterprise is requested but overlay
    # absent. Uses _overlay_extension_names() so core builtins (e.g. the
    # notification sink) never read as an enterprise overlay.
    check_enterprise_overlay_requested(_overlay_extension_names())

    # Step 2b (GUARD-01): fail loud if multi_tenant is configured but no
    # tenancy-providing overlay is loaded.
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

    # Step 4b: register the built-in notification sink AFTER edition
    # resolution — CRITICAL ordering. It writes into the same `_extensions`
    # registry that init_edition()/check_enterprise_overlay_requested() read
    # to detect the edition; registering it BEFORE init_edition made
    # `list_extensions()` non-empty, so a plain community deployment
    # mis-detected as `enterprise`. Runs unconditionally for both API and
    # worker so the sink is present in both processes (IN-01).
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
    # Community's DefaultBillingExtension.on_startup is a no-op. Each
    # extension gets a 10s timeout and its own try/except, so one failing
    # extension can't block startup or take down another's dispatch.
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

    # fix(#1315): initialize the binary tile cache here too. It used to live
    # in the API lifespan alone, so get_tile_cache() returned None in the
    # worker and every post-swap MVT purge (fix(#394) B-019 — reupload_file,
    # reupload_service, refresh_postgis) evicted nothing from the worker.
    # The worker gets no in-memory fallback: it never reads tiles, so a
    # process-local LRU there would be a purge that evicts nothing and says
    # it worked. `app is not None` is the right discriminator because the
    # FastAPI app is the only process a process-local cache could ever serve.
    init_tile_cache(in_memory_fallback=app is not None)

    # Step 10 (ISO-02): mode-gated idempotent RLS enablement. In
    # single_tenant: no-op. In multi_tenant: enables + FORCEs RLS on the
    # tenant-shared tables so the 0006_tenant_rls FORCE policies become
    # active. Checks pg_class flags before any ALTER TABLE, so concurrent
    # multi-worker boots don't contend on ACCESS EXCLUSIVE locks. A mode
    # flip needs no new migration — this enables the already-present policies.
    from app.core.db.rls import apply_tenancy_rls_from_engine  # noqa: E402

    await apply_tenancy_rls_from_engine()

    return edition_info
