"""Granular permissions: capability constants, default role matrix, and effective permissions.

Provides the foundation for capability-based access control. Each role has a set of
boolean capabilities. The default matrix preserves current behavior (viewer=view+export,
editor=+upload+edit+create, admin=all). Admins can customize via PersistentConfig.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Capability constants
# ---------------------------------------------------------------------------

UPLOAD = "upload"
CREATE_LAYERS = "create_layers"
EXPORT = "export"
EDIT_METADATA = "edit_metadata"
MANAGE_COLLECTIONS = "manage_collections"
USE_AI_CHAT = "use_ai_chat"
MANAGE_USERS = "manage_users"
MANAGE_SETTINGS = "manage_settings"

ALL_CAPABILITIES: list[str] = [
    UPLOAD,
    CREATE_LAYERS,
    EXPORT,
    EDIT_METADATA,
    MANAGE_COLLECTIONS,
    USE_AI_CHAT,
    MANAGE_USERS,
    MANAGE_SETTINGS,
]

# ---------------------------------------------------------------------------
# Default role permissions (matches current role behavior)
# ---------------------------------------------------------------------------

DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    "viewer": {
        UPLOAD: False,
        CREATE_LAYERS: False,
        EXPORT: True,
        EDIT_METADATA: False,
        MANAGE_COLLECTIONS: False,
        USE_AI_CHAT: False,
        MANAGE_USERS: False,
        MANAGE_SETTINGS: False,
    },
    "editor": {
        UPLOAD: True,
        CREATE_LAYERS: True,
        EXPORT: True,
        EDIT_METADATA: True,
        MANAGE_COLLECTIONS: True,
        USE_AI_CHAT: True,
        MANAGE_USERS: False,
        MANAGE_SETTINGS: False,
    },
    "admin": {
        UPLOAD: True,
        CREATE_LAYERS: True,
        EXPORT: True,
        EDIT_METADATA: True,
        MANAGE_COLLECTIONS: True,
        USE_AI_CHAT: True,
        MANAGE_USERS: True,
        MANAGE_SETTINGS: True,
    },
}

# ---------------------------------------------------------------------------
# Lockout prevention
# ---------------------------------------------------------------------------


def validate_permission_matrix(matrix: Any) -> None:
    """Validate a permission matrix dict.

    Raises ValueError if:
    - matrix is not a dict
    - admin role is missing manage_users or manage_settings (lockout prevention)
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


# ---------------------------------------------------------------------------
# Effective permissions (DB override merged with defaults)
# ---------------------------------------------------------------------------


async def get_effective_permissions(db: AsyncSession) -> dict[str, dict[str, bool]]:
    """Return the effective permission matrix, merging DB overrides with defaults.

    New capabilities added in code updates will get their default values even if
    a custom matrix was saved before the capability existed.
    """
    from app.persistent_config import ROLE_PERMISSIONS

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
