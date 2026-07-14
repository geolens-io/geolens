"""Granular permissions: capability constants, default role matrix, and effective permissions.

Provides the foundation for capability-based access control. Each role has a set of
boolean capabilities. The default matrix preserves current behavior (viewer=view+export,
editor=+upload+edit+create, admin=all). Admins can customize via PersistentConfig.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ALL_CAPABILITIES,
    CREATE_LAYERS,
    DEFAULT_ROLE_PERMISSIONS,
    EDIT_METADATA,
    EXPORT,
    MANAGE_COLLECTIONS,
    MANAGE_SETTINGS,
    MANAGE_TENANTS,
    MANAGE_USERS,
    UPLOAD,
    USE_AI_CHAT,
)

__all__ = [
    "ALL_CAPABILITIES",
    "CREATE_LAYERS",
    "DEFAULT_ROLE_PERMISSIONS",
    "EDIT_METADATA",
    "EXPORT",
    "MANAGE_COLLECTIONS",
    "MANAGE_SETTINGS",
    "MANAGE_TENANTS",
    "MANAGE_USERS",
    "UPLOAD",
    "USE_AI_CHAT",
    "get_effective_permissions",
    "user_has_capability",
    "validate_permission_matrix",
]

# ---------------------------------------------------------------------------
# Lockout prevention
# ---------------------------------------------------------------------------


def validate_permission_matrix(matrix: Any) -> None:
    """Validate a permission matrix dict.

    Raises ValueError if:
    - matrix is not a dict
    - admin role is missing manage_users or manage_settings (lockout prevention)
    - any stored role has manage_tenants (fleet-control escalation prevention)
    - a non-admin role has manage_users or manage_settings (escalation prevention)

    ``manage_tenants`` is intentionally unavailable to *every* database-stored
    role, including ``admin``. Fleet operators receive that capability through
    the deployment's out-of-band identity extension; allowing it in the
    tenant-editable matrix would let a per-tenant admin promote themselves into
    the fleet control plane.
    """
    if not isinstance(matrix, dict):
        raise ValueError("Permission matrix must be a dict")

    admin = matrix.get("admin")
    if admin is None:
        raise ValueError("Permission matrix must include 'admin' role")
    if not isinstance(admin, dict):
        raise ValueError("Permission matrix role 'admin' must be an object")

    for role_name, caps in matrix.items():
        if not isinstance(caps, dict):
            raise ValueError(f"Permission matrix role '{role_name}' must be an object")

    if not admin.get(MANAGE_USERS, False):
        raise ValueError(
            "Cannot remove manage_users from admin role (lockout prevention)"
        )
    if not admin.get(MANAGE_SETTINGS, False):
        raise ValueError(
            "Cannot remove manage_settings from admin role (lockout prevention)"
        )
    # Fleet control-plane authority is never assignable through PersistentConfig.
    # Check every role (including admin and custom roles) before the admin-only
    # capability checks below.
    for role_name, caps in matrix.items():
        if caps.get(MANAGE_TENANTS, False):
            raise ValueError(
                f"Cannot grant manage_tenants to stored role '{role_name}' "
                "(fleet-superadmin capability is granted out-of-band)"
            )

    # Prevent granting admin-only capabilities to non-admin roles
    for role_name, caps in matrix.items():
        if role_name == "admin":
            continue
        if caps.get(MANAGE_USERS, False):
            raise ValueError(
                f"Cannot grant manage_users to non-admin role '{role_name}'"
            )
        if caps.get(MANAGE_SETTINGS, False):
            raise ValueError(
                f"Cannot grant manage_settings to non-admin role '{role_name}'"
            )


# ---------------------------------------------------------------------------
# Effective permissions (DB override merged with defaults)
# ---------------------------------------------------------------------------


async def user_has_capability(db: AsyncSession, user: Any, capability: str) -> bool:
    """Return True if *user* holds *capability* via any of their assigned roles.

    Used for break-glass exemptions (e.g. DOMAIN-04 manage_settings bypass).
    Resolves roles via get_user_roles (catalog.authorization) and checks the
    effective permission matrix; does NOT add DB code to domain_validation.py
    (that module is DB-free by contract, T-1235 purity gate).

    Args:
        db:         Async DB session.
        user:       Any object with a ``.id`` UUID attribute (User ORM or Identity).
        capability: Capability string constant, e.g. MANAGE_SETTINGS.

    Returns:
        True if any of the user's roles grant the requested capability.
    """
    from app.modules.catalog.authorization import (
        get_user_roles,
    )  # LAZY — avoids circular

    roles = await get_user_roles(db, user)
    matrix = await get_effective_permissions(db)
    return any(matrix.get(role, {}).get(capability, False) for role in roles)


async def get_effective_permissions(db: AsyncSession) -> dict[str, dict[str, bool]]:
    """Return the effective permission matrix, merging DB overrides with defaults.

    New capabilities added in code updates will get their default values even if
    a custom matrix was saved before the capability existed.
    """
    from app.core.persistent_config import ROLE_PERMISSIONS

    stored: dict = await ROLE_PERMISSIONS.get(db)

    # Deep merge: start from defaults, overlay stored values
    result: dict[str, dict[str, bool]] = copy.deepcopy(DEFAULT_ROLE_PERMISSIONS)
    for role, caps in stored.items():
        if role not in result:
            # Custom role added by admin -- take as-is
            result[role] = {cap: False for cap in ALL_CAPABILITIES}
        if isinstance(caps, dict):
            result[role].update(caps)

    # Defense in depth for rows written before this invariant existed (or by a
    # privileged/manual DB operation): the tenant-editable matrix is never an
    # authority source for fleet control. Permission extensions may still grant
    # manage_tenants out-of-band after this baseline matrix is resolved.
    for caps in result.values():
        caps[MANAGE_TENANTS] = False

    return result
