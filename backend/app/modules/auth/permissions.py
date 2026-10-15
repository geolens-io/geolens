"""Granular permissions: capability constants, default role matrix, and effective permissions.

Provides the foundation for capability-based access control. Each role has a set of
boolean capabilities. The default matrix preserves current behavior (viewer=view+export,
editor=+upload+edit+create, admin=all). Admins can customize via PersistentConfig.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import Role, User, UserRole
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
    "get_user_roles",
    "user_has_capability",
    "validate_permission_matrix",
]


def validate_permission_matrix(matrix: Any) -> None:
    """Validate a permission matrix dict.

    Raises ValueError if:
    - matrix is not a dict
    - admin role is missing manage_users or manage_settings (lockout prevention)
    - any stored role has manage_tenants (fleet-control escalation prevention)
    - a non-admin role has manage_users or manage_settings (escalation prevention)

    ``manage_tenants`` is intentionally unavailable to every database-stored
    role, including admin — fleet operators get it via the deployment's
    out-of-band identity extension; allowing it here would let a per-tenant
    admin promote themselves into the fleet control plane.
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
# Role resolution
# ---------------------------------------------------------------------------


async def get_user_roles(db: AsyncSession, user: Identity) -> set[str]:
    """Get the set of role names for a user.

    Replaces the per-router ``_get_user_roles()`` duplicates. Lives here rather
    than in ``catalog.authorization`` (its home until this move) because the
    query reads the auth-owned ``Role``/``UserRole`` tables and touches nothing
    catalog; ``catalog.authorization`` re-exports it so its callers are
    unaffected.
    """
    result = await db.execute(_role_names(user.id))
    return {row[0] for row in result.all()}


def _role_names(user_id: Any) -> Select[tuple[str]]:
    return (
        select(Role.name)
        .join(UserRole, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )


def user_standing_columns(user_id: Any) -> tuple[ColumnElement, ColumnElement]:
    """``user_id``'s role names (``roles``, an array) and whether the account
    is active (``active``, NULL for no account), as columns for another
    statement to select."""
    return (
        func.array(_role_names(user_id).scalar_subquery()).label("roles"),
        select(User.is_active)
        .where(User.id == user_id)
        .scalar_subquery()
        .label("active"),
    )


_ADMITTED_CAPABILITIES = "admitted_capabilities"


def admit_capabilities(
    db: AsyncSession, user_id: Any, capabilities: Any, matrix: dict
) -> None:
    """Record that ``require_permission`` admitted ``user_id`` under
    ``capabilities``, read against ``matrix``, for this session."""
    admitted = db.info.setdefault(_ADMITTED_CAPABILITIES, {})
    held, _ = admitted.get(user_id, (frozenset(), matrix))
    admitted[user_id] = (held | frozenset(capabilities), matrix)


def admitted_capabilities(
    db: AsyncSession, user_id: Any
) -> tuple[frozenset[str], dict]:
    """The capabilities and matrix :func:`admit_capabilities` recorded for
    ``user_id`` in this session; none when nothing was recorded."""
    return db.info.get(_ADMITTED_CAPABILITIES, {}).get(user_id, (frozenset(), {}))


# ---------------------------------------------------------------------------
# Effective permissions (DB override merged with defaults)
# ---------------------------------------------------------------------------


async def user_has_capability(db: AsyncSession, user: Any, capability: str) -> bool:
    """Return True if *user* holds *capability* via any of their assigned roles.

    Used for break-glass exemptions (e.g. DOMAIN-04 manage_settings bypass).
    Resolves roles via get_user_roles and checks the effective permission
    matrix; does NOT add DB code to domain_validation.py (DB-free by contract,
    T-1235 purity gate). *user* may be any object with a ``.id`` UUID
    attribute (User ORM or Identity).
    """
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
