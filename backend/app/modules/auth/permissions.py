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
    - a non-admin role has manage_users, manage_settings, or manage_tenants (escalation prevention)

    Note: manage_tenants is intentionally NOT subject to admin lockout prevention.
    Per CR-02 (Phase 1211) it is a fleet-superadmin-only capability that defaults
    to False even for the admin role, so the default matrix legitimately omits it
    from admin — gating it here would reject the default config on round-trip.
    Escalation prevention (non-admin roles may not hold it) still applies below.
    """
    if not isinstance(matrix, dict):
        raise ValueError("Permission matrix must be a dict")

    admin = matrix.get("admin")
    if admin is None:
        raise ValueError("Permission matrix must include 'admin' role")

    if not admin.get(MANAGE_USERS, False):
        raise ValueError(
            "Cannot remove manage_users from admin role (lockout prevention)"
        )
    if not admin.get(MANAGE_SETTINGS, False):
        raise ValueError(
            "Cannot remove manage_settings from admin role (lockout prevention)"
        )
    # Prevent granting admin-only capabilities to non-admin roles
    for role_name, caps in matrix.items():
        if role_name == "admin" or not isinstance(caps, dict):
            continue
        if caps.get(MANAGE_USERS, False):
            raise ValueError(
                f"Cannot grant manage_users to non-admin role '{role_name}'"
            )
        if caps.get(MANAGE_SETTINGS, False):
            raise ValueError(
                f"Cannot grant manage_settings to non-admin role '{role_name}'"
            )
        if caps.get(MANAGE_TENANTS, False):
            raise ValueError(
                f"Cannot grant manage_tenants to non-admin role '{role_name}'"
            )


# ---------------------------------------------------------------------------
# Effective permissions (DB override merged with defaults)
# ---------------------------------------------------------------------------


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

    return result
