"""Tenancy MODE axis helper.

TSEAM-03 (Phase 1207-02): orthogonal tenancy mode — independent of the
Community/Enterprise edition binary. Read by tenancy-aware code only.

Edition stays binary (community|enterprise). Mode controls the tenancy
posture of the deployment and is ORTHOGONAL to edition.

Usage::

    from app.core.tenancy import is_multi_tenant

    if is_multi_tenant():
        # multi_tenant path — requires cloud overlay + 1208 RLS
        ...
"""

from __future__ import annotations

#: Literal value for single-tenant mode (default; byte-identical to pre-1207 behavior).
TENANCY_MODE_SINGLE = "single_tenant"

#: Literal value for multi-tenant mode (requires cloud overlay + 1208 RLS).
TENANCY_MODE_MULTI = "multi_tenant"


def is_multi_tenant() -> bool:
    """Return True iff GEOLENS_TENANCY_MODE is set to ``multi_tenant``.

    Mirrors the shape of :func:`app.core.edition.is_enterprise` — a single
    boolean predicate with a safe default (False = single_tenant).

    Reading happens at call-time so tests can reload :mod:`app.core.config`
    and observe the new value without a process restart.
    """
    from app.core.config import settings

    return settings.geolens_tenancy_mode == TENANCY_MODE_MULTI


def tenant_bound_scope(resource: str) -> str:
    """Bind a signed resource scope to the active hosted tenant.

    Community/single-tenant callers receive the original resource string
    byte-for-byte. Hosted callers must have an explicit request or worker
    tenant; silently minting a legacy unbound scope would make the signature
    unusable at best and replayable across tenant hosts at worst.
    """
    if not is_multi_tenant():
        return resource

    from app.core.db.tenant_session import current_tenant_var

    tenant_id = current_tenant_var.get()
    if tenant_id is None:
        raise RuntimeError(
            "Tenant context is required for a tenant-bound resource scope"
        )
    return f"{tenant_id}:{resource}"
