"""FastAPI dependency surface for the EntitlementPort seam.

Exposes two dependency factories:

- ``require_entitlement(*features)`` — ensure the current tenant's plan
  includes all named features; raises HTTP 403 on denial.
- ``enforce_limit(request, dimension, n)`` — delegate a numeric limit check
  to the registered EntitlementPort; the grant-all default never raises.

Both are ORTHOGONAL to ``require_enterprise()`` (binary edition gate) and
``require_permission(*capabilities)`` (per-user RBAC via PermissionExtension).

In Community/Enterprise ``DefaultEntitlementPort`` is grant-all (fail-OPEN
by design — see its class docstring). The cloud overlay registers a real
implementation backed by the ``tenant_entitlements`` table
(webhook-synced from Stripe).

Request-state cache: ``request.state._entitlement_summary`` stores resolved
feature flags for the current request, mirroring
``request.state._effective_permissions`` in
``app.modules.auth.dependencies.require_permission``, so a route with
multiple ``require_entitlement`` dependencies avoids redundant port calls.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from app.platform.extensions import get_entitlement_port


def require_entitlement(*features: str) -> Any:
    """Factory returning a FastAPI dependency that enforces feature entitlement.

    Resolves ``get_entitlement_port()``, checks each named feature via
    ``port.has_feature(feature)``, and raises HTTP 403 if the current tenant
    is not entitled. Under the grant-all ``DefaultEntitlementPort``
    (OSS/Enterprise) this dependency is always inert.

    Resolved flags are cached on ``request.state._entitlement_summary`` so
    repeated checks within one request avoid redundant port calls.

    Usage::

        @router.get("/advanced", dependencies=[Depends(require_entitlement("advanced_analytics"))])
        async def advanced_endpoint(): ...
    """

    async def _entitlement_checker(request: Request) -> None:
        # Mirrors request.state._effective_permissions in dependencies.py.
        cached: dict[str, bool] | None = getattr(
            request.state, "_entitlement_summary", None
        )
        if cached is None:
            cached = {}
            request.state._entitlement_summary = cached

        port = get_entitlement_port()

        for feature in features:
            if feature in cached:
                entitled = cached[feature]
            else:
                entitled = await port.has_feature(feature)
                cached[feature] = entitled

            if not entitled:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Feature not available on current plan: {feature}",
                )

    return _entitlement_checker


async def enforce_limit(request: Request, dimension: str, n: int) -> None:
    """Dependency helper that delegates a numeric limit check to the EntitlementPort.

    Calls ``await port.enforce_limit(dimension, n)``; the port raises if
    ``n`` exceeds the tenant's quota for ``dimension``. Under the grant-all
    ``DefaultEntitlementPort`` (OSS/Enterprise) this is always a no-op.

    Intended for use as a callable within route handlers or a ``Depends``
    chain::

        await enforce_limit(request, "datasets", current_count)

    The cloud overlay provides the real implementation that reads the
    ``tenant_entitlements`` table and enforces plan-level hard caps.
    """
    port = get_entitlement_port()
    await port.enforce_limit(dimension, n)
