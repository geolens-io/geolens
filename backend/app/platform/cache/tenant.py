"""Tenant partitioning for caches that contain request-visible data."""

from __future__ import annotations

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant


def tenant_cache_context_available() -> bool:
    """Return whether request-visible caches are safe in this context.

    Trusted unscoped hosts can legitimately reach anonymous catalog routes in
    hosted mode. Those requests query the RLS-protected database directly and
    must never read or populate a fleet-shared fallback cache entry.
    """
    if not is_multi_tenant():
        return True

    tenant_id = current_tenant_var.get()
    if tenant_id is None:
        return False
    tenant_data_schema(tenant_id)
    return True


def tenant_cache_key(key: str) -> str:
    """Return *key* scoped to the verified request or worker tenant.

    Single-tenant deployments keep their historical keys byte-for-byte. In
    multi-tenant mode the active tenant UUID is validated through the same
    schema helper used by data-plane SQL, then appended to the key. Appending
    preserves broad invalidation prefixes such as ``catalog:*``.

    Missing or malformed multi-tenant context fails closed before a cache can
    be read or populated.
    """
    if not is_multi_tenant():
        return key

    tenant_id = current_tenant_var.get()
    tenant_data_schema(tenant_id)
    assert tenant_id is not None  # tenant_data_schema() rejects None above
    return f"{key}:tenant:{tenant_id.lower()}"
