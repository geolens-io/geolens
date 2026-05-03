"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
Relocated from the deleted auth visibility module (Phase 213).
"""

import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import Role, UserRole
from app.platform.extensions import get_permission_extension


class DatasetVisibility(str, enum.Enum):
    """Controls who can see a dataset."""

    PUBLIC = "public"
    RESTRICTED = "restricted"
    PRIVATE = "private"


def apply_visibility_filter(
    stmt: Select[Any],
    user: Identity | None,
    user_roles: set[str],
    record_cls: Any,
    grant_cls: Any | None = None,
) -> Select[Any]:
    """Filter a query based on visibility and user permissions.

    After the records+datasets refactor, visibility and created_by
    live on the Record model. The grant_cls still references datasets
    via dataset_id.

    Args:
        stmt: An existing SQLAlchemy Select statement.
        user: The currently authenticated User, or None for anonymous access.
        user_roles: Set of role name strings for the user.
        record_cls: The model class with visibility/created_by fields (Record).
        grant_cls: The DatasetGrant model class (optional).

    Returns:
        The filtered Select statement.
    """
    return get_permission_extension().filter_visible(
        stmt, user, user_roles, record_cls, grant_cls
    )


async def get_user_roles(db: AsyncSession, user: Identity) -> set[str]:
    """Get the set of role names for a user.

    Replaces the per-router ``_get_user_roles()`` duplicates.
    """
    result = await db.execute(
        select(Role.name)
        .join(UserRole, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
    )
    return {row[0] for row in result.all()}


async def check_dataset_access_or_anonymous(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: Identity | None
) -> set[str]:
    """Enforce visibility for both authenticated and anonymous users.

    Returns the resolved user_roles set (empty for anonymous).
    Anonymous users may only access public + published datasets.
    Authenticated users follow the full RBAC rules via check_dataset_access().
    """
    if user is None:
        allowed = await get_permission_extension().can_access_dataset(
            db,
            dataset,
            dataset_id,
            None,
            user_roles=set(),
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        return set()
    return await check_dataset_access(db, dataset, dataset_id, user)


async def check_dataset_access(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: Identity,
    *,
    user_roles: set[str] | None = None,
) -> set[str]:
    """Enforce RBAC visibility on a single dataset. Raises 404 if access denied.

    Returns the resolved user_roles set so callers can reuse it downstream.

    After refactor, visibility and created_by are on dataset.record.

    Logic:
    - Admins: always allowed
    - Private datasets: only the owner can access
    - Restricted datasets: user must have a grant via their roles
    - Public datasets: always allowed
    """
    if user_roles is None:
        user_roles = await get_user_roles(db, user)

    allowed = await get_permission_extension().can_access_dataset(
        db,
        dataset,
        dataset_id,
        user,
        user_roles=user_roles,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    return user_roles
