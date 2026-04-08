"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
"""

import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserRole


class DatasetVisibility(str, enum.Enum):
    """Controls who can see a dataset."""

    PUBLIC = "public"
    RESTRICTED = "restricted"
    PRIVATE = "private"


def apply_visibility_filter(
    stmt: Select[Any],
    user: User | None,
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
    # Admin sees everything
    if "admin" in user_roles:
        return stmt

    # Anonymous users see only public, published datasets
    if user is None:
        return stmt.where(
            record_cls.visibility == DatasetVisibility.PUBLIC,
            record_cls.record_status == "published",
        )

    conditions = [
        # Public datasets: visible to all authenticated users
        record_cls.visibility == DatasetVisibility.PUBLIC,
        # Private datasets: only the owner can see them
        and_(
            record_cls.visibility == DatasetVisibility.PRIVATE,
            record_cls.created_by == user.id,
        ),
    ]

    # Restricted datasets: user must have a grant via their roles
    if grant_cls is not None:
        conditions.append(
            and_(
                record_cls.visibility == DatasetVisibility.RESTRICTED,
                record_cls.id.in_(
                    select(grant_cls.dataset_id)
                    .join(UserRole, grant_cls.role_id == UserRole.role_id)
                    .where(UserRole.user_id == user.id)
                ),
            )
        )

    # Non-admin users can only see published datasets, or their own drafts/unpublished
    status_filter = or_(
        record_cls.record_status == "published",
        record_cls.created_by == user.id,
    )
    return stmt.where(and_(or_(*conditions), status_filter))


async def get_user_roles(db: AsyncSession, user: User) -> set[str]:
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
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: User | None
) -> None:
    """Enforce visibility for both authenticated and anonymous users.

    Anonymous users may only access public + published datasets.
    Authenticated users follow the full RBAC rules via check_dataset_access().
    """
    if user is None:
        record = dataset.record
        if record.visibility != "public" or record.record_status != "published":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        return
    await check_dataset_access(db, dataset, dataset_id, user)


async def check_dataset_access(
    db: AsyncSession, dataset: Any, dataset_id: uuid.UUID, user: User
) -> None:
    """Enforce RBAC visibility on a single dataset. Raises 404 if access denied.

    After refactor, visibility and created_by are on dataset.record.

    Logic:
    - Admins: always allowed
    - Private datasets: only the owner can access
    - Restricted datasets: user must have a grant via their roles
    - Public datasets: always allowed
    """
    from app.datasets.models import DatasetGrant

    user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        return

    record = dataset.record

    # Block access to non-published datasets for non-owners
    if record.record_status != "published" and record.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if record.visibility == "private" and record.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if record.visibility == "restricted":
        grant_result = await db.execute(
            select(DatasetGrant.dataset_id)
            .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
            .where(
                DatasetGrant.dataset_id == dataset_id,
                UserRole.user_id == user.id,
            )
        )
        if grant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
