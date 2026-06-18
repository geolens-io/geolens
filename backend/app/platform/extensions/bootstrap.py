"""Shared bootstrap helper for API lifespan and worker startup.

WORK-01: Extract ONE shared ``bootstrap()`` helper that performs the full
extension-load + edition-init + storage/cache-init sequence. Call it from
BOTH ``api/main.py`` lifespan AND ``worker.main()`` so the two entrypoints
cannot drift into different bootstrap states.

WORK-02: ``assert_enterprise_ports_resolved()`` performs an affirmative
post-bootstrap assertion: under ``GEOLENS_EDITION=enterprise``, every expected
single-slot port MUST be resolved to a non-Default implementation or the
process raises ``RuntimeError`` and refuses to start.

References: WORK-01, WORK-02
"""

from __future__ import annotations

import asyncio
import os
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

#: Single-slot port accessor names + their Default class names.
#: Any port whose runtime class name matches the Default name is considered
#: un-resolved under GEOLENS_EDITION=enterprise and causes a loud failure.
_ENTERPRISE_PORT_CHECKS: list[tuple[str, str]] = [
    ("processing_port", "DefaultProcessingPort"),
    ("catalog_port", "DefaultCatalogPort"),
    ("permission", "DefaultPermissionExtension"),
    ("identity", "DefaultIdentityExtension"),
    ("workflow", "DefaultWorkflowExtension"),
]


def assert_enterprise_ports_resolved() -> None:
    """Assert every expected single-slot port is NOT the Default* impl.

    WORK-02 — Called by the worker after ``bootstrap()`` completes. Under
    ``GEOLENS_EDITION=enterprise`` all expected single-slot ports MUST be
    resolved to non-Default implementations.  If any port is still the
    Default impl, this function raises ``RuntimeError`` naming every
    still-Default port and pointing at the build-time-bake remedy.

    Under community / no GEOLENS_EDITION: no-op (returns silently).

    Logs the resolved implementation class for each port at INFO level
    regardless of edition — makes silent-community-fallback observable in
    production logs (WORK-02 observability clause).
    """
    from app.platform.extensions import (
        get_catalog_port,
        get_identity_extension,
        get_permission_extension,
        get_processing_port,
        get_workflow_extension,
    )

    edition_val = os.environ.get("GEOLENS_EDITION", "").lower().strip()

    # Collect resolved port names + their class names for logging + assertion.
    resolved: list[tuple[str, str]] = []
    for port_key, _default_cls_name in _ENTERPRISE_PORT_CHECKS:
        if port_key == "processing_port":
            port = get_processing_port()
        elif port_key == "catalog_port":
            port = get_catalog_port()
        elif port_key == "permission":
            port = get_permission_extension()
        elif port_key == "identity":
            port = get_identity_extension()
        elif port_key == "workflow":
            port = get_workflow_extension()
        else:
            continue
        resolved.append((port_key, type(port).__name__))

    # Log resolved impl per port (observable signal even in community mode).
    for port_key, cls_name in resolved:
        logger.info(
            "Extension port resolved",
            port=port_key,
            impl=cls_name,
        )

    if edition_val != "enterprise":
        # Not enterprise — no assertion required.
        return

    # Build a lookup from port_key → expected Default class name
    _default_by_key: dict[str, str] = {k: v for k, v in _ENTERPRISE_PORT_CHECKS}
    still_default: list[str] = [
        f"{port_key} ({cls_name})"
        for port_key, cls_name in resolved
        if cls_name == _default_by_key.get(port_key)
    ]

    if still_default:
        still_list = ", ".join(still_default)
        raise RuntimeError(
            f"GEOLENS_EDITION=enterprise is set but the following single-slot ports "
            f"are still the Default community implementations: [{still_list}]. "
            f"The enterprise overlay must register non-Default implementations for "
            f"all expected single-slot ports before the worker starts. "
            f"Pre-bake the overlay into the image at build time using "
            f"'docker build --build-arg INSTALL_ENTERPRISE_OVERLAY=1 ...' "
            f"(see ARG INSTALL_ENTERPRISE_OVERLAY in the Dockerfile). "
            f"References: WORK-02."
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
    check_enterprise_overlay_requested(list_extensions())

    # Step 2b: GUARD-01 edition-half — fail loud if multi_tenant is configured
    # but no tenancy-providing overlay is loaded (T-1207-06, Phase 1207-02).
    check_tenancy_mode_supported(list_extensions())

    # Step 3: Resolve the edition singleton from loaded extensions.
    init_edition(list_extensions())
    edition_info = get_edition()

    # Step 4: Log detected edition.
    logger.info(
        "Edition detected",
        edition=edition_info.edition,
        features=list(edition_info.features),
    )

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
