"""Admin service: user CRUD, role assignment, and catalog stats."""

import logging
import uuid

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import CatalogStatsResponse, EmbeddingStatsResponse, UserUpdate
from app.auth.models import ApiKey, Role, User, UserRole
from app.auth.providers.local import hash_password
from app.datasets.models import Dataset, Record

logger = logging.getLogger(__name__)


class AdminService:
    """Handles admin-level user management operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _ensure_not_last_admin(self, user: User, action: str = "modify") -> None:
        """Raise ValueError if this is the last admin user."""
        user_roles = {r.name for r in user.roles}
        if "admin" in user_roles:
            admin_count_result = await self.db.execute(
                select(func.count())
                .select_from(UserRole)
                .join(Role, UserRole.role_id == Role.id)
                .where(Role.name == "admin", UserRole.user_id != user.id)
            )
            other_admins = admin_count_result.scalar() or 0
            if other_admins == 0:
                raise ValueError(f"Cannot {action} the last admin user")

    async def create_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
        role_name: str = "viewer",
    ) -> User:
        """Create a new user with the specified role.

        Raises ValueError if username/email is taken or role not found.
        """
        # Check username uniqueness (case-insensitive)
        existing = await self.db.execute(
            select(User).where(func.lower(User.username) == func.lower(username))
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("Username already taken")

        # Check email uniqueness if provided
        if email is not None:
            existing_email = await self.db.execute(
                select(User).where(func.lower(User.email) == func.lower(email))
            )
            if existing_email.scalar_one_or_none() is not None:
                raise ValueError("Email already registered")

        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email,
            status="active",
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()

        # Assign specified role
        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found")

        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def deactivate_user(
        self, user_id: uuid.UUID, current_user_id: uuid.UUID | None = None
    ) -> User:
        """Deactivate a user by ID.

        Raises ValueError if user not found, self-deactivation, or last admin.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        if current_user_id is not None and user_id == current_user_id:
            raise ValueError("Cannot deactivate your own account")

        await self._ensure_not_last_admin(user, "deactivate")

        # Note: sets is_active=False while keeping status="active".
        # Auth checks enforce BOTH (status=="active" AND is_active==True),
        # so the user is effectively locked out. The list_users endpoint
        # interprets "deactivated" as status="active" + is_active=False.
        user.is_active = False
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update_user(self, user_id: uuid.UUID, updates: UserUpdate) -> User:
        """Update a user's fields and/or role.

        Raises ValueError if user not found or role not found.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        # Apply non-None scalar fields
        if updates.email is not None:
            # Check email uniqueness
            existing_email = await self.db.execute(
                select(User).where(
                    func.lower(User.email) == func.lower(updates.email),
                    User.id != user_id,
                )
            )
            if existing_email.scalar_one_or_none() is not None:
                raise ValueError("Email already registered")
            user.email = updates.email

        if updates.is_active is not None:
            if updates.is_active is False:
                await self._ensure_not_last_admin(user, "deactivate")
            user.is_active = updates.is_active

        # Handle role change
        if updates.role is not None:
            # Find the new role
            role_result = await self.db.execute(
                select(Role).where(Role.name == updates.role)
            )
            new_role = role_result.scalar_one_or_none()
            if new_role is None:
                raise ValueError(f"Role '{updates.role}' not found")

            # Last-admin guard: prevent demoting the sole admin
            user_roles = {r.name for r in user.roles}
            if "admin" in user_roles and updates.role != "admin":
                admin_count_result = await self.db.execute(
                    select(func.count())
                    .select_from(UserRole)
                    .join(Role, UserRole.role_id == Role.id)
                    .where(Role.name == "admin", UserRole.user_id != user_id)
                )
                other_admins = admin_count_result.scalar() or 0
                if other_admins == 0:
                    raise ValueError("Cannot demote the last admin user")

            # Remove existing roles
            await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
            # Add new role
            self.db.add(UserRole(user_id=user_id, role_id=new_role.id))

        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def list_users(
        self,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        """List users with pagination and optional status/search filter.

        Returns (users, total_count).
        """
        count_query = select(func.count()).select_from(User)
        list_query = select(User).order_by(User.created_at)

        if status == "deactivated":
            deactivated = (User.status == "active") & (User.is_active == False)  # noqa: E712
            count_query = count_query.where(deactivated)
            list_query = list_query.where(deactivated)
        elif status is not None:
            count_query = count_query.where(User.status == status)
            list_query = list_query.where(User.status == status)

        if search is not None:
            pattern = f"%{search}%"
            search_filter = User.username.ilike(pattern) | User.email.ilike(pattern)
            count_query = count_query.where(search_filter)
            list_query = list_query.where(search_filter)

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        result = await self.db.execute(list_query.offset(skip).limit(limit))
        users = list(result.scalars().all())

        return users, total

    async def get_user(self, user_id: uuid.UUID) -> User:
        """Get a single user by ID.

        Raises ValueError if user not found.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        return user

    async def approve_user(self, user_id: uuid.UUID, role_name: str) -> User:
        """Approve a pending user: set active, assign role.

        Raises ValueError if user not found, not pending, or role not found.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        if user.status != "pending":
            raise ValueError("User is not in pending status")

        user.status = "active"
        user.is_active = True

        # Assign the chosen role
        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found")

        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def reject_user(self, user_id: uuid.UUID) -> None:
        """Reject a pending user by hard-deleting them.

        Raises ValueError if user not found or not pending.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        if user.status != "pending":
            raise ValueError("User is not in pending status")

        await self.db.delete(user)
        await self.db.flush()

    async def delete_user(self, user_id: uuid.UUID, current_user_id: uuid.UUID) -> None:
        """Hard-delete a user.

        Raises ValueError for self-deletion, last-admin deletion, or not found.
        FK SET NULL handles audit_logs, datasets, ingest_jobs automatically.
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        if user_id == current_user_id:
            raise ValueError("Cannot delete your own account")

        await self._ensure_not_last_admin(user, "delete")

        # Delete related records that have CASCADE or need explicit cleanup
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self.db.execute(delete(ApiKey).where(ApiKey.user_id == user_id))

        # Hard delete the user (FK SET NULL handles audit_logs, datasets, ingest_jobs)
        await self.db.delete(user)
        await self.db.flush()

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        user_id: uuid.UUID | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        """List ingestion jobs with optional filters. Returns (rows, total)."""
        from app.auth.models import User as UserModel
        from app.jobs.models import IngestJob

        filters = []
        if status is not None:
            filters.append(IngestJob.status == status)
        if user_id is not None:
            filters.append(IngestJob.created_by == user_id)
        if search is not None:
            filters.append(IngestJob.source_filename.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(IngestJob)
        for f in filters:
            count_stmt = count_stmt.where(f)
        total = (await self.db.execute(count_stmt)).scalar_one()

        list_stmt = (
            select(IngestJob, UserModel.username)
            .outerjoin(UserModel, IngestJob.created_by == UserModel.id)
            .order_by(IngestJob.created_at.desc())
        )
        for f in filters:
            list_stmt = list_stmt.where(f)
        list_stmt = list_stmt.offset(skip).limit(limit)
        rows = (await self.db.execute(list_stmt)).all()

        return rows, total

    async def get_embedding_stats(self) -> EmbeddingStatsResponse:
        """Return embedding coverage statistics."""
        try:
            total_result = await self.db.execute(
                text("SELECT COUNT(*) FROM catalog.records")
            )
            total_records = total_result.scalar_one()

            embedded_result = await self.db.execute(
                text("SELECT COUNT(DISTINCT record_id) FROM catalog.record_embeddings")
            )
            embedded_records = embedded_result.scalar_one()
        except Exception:
            logger.warning("Failed to query embedding stats", exc_info=True)
            return EmbeddingStatsResponse(
                total_records=0,
                embedded_records=0,
                missing_records=0,
                coverage_percent=0.0,
            )

        missing_records = total_records - embedded_records
        coverage_percent = (
            (embedded_records / total_records * 100) if total_records > 0 else 0.0
        )
        return EmbeddingStatsResponse(
            total_records=total_records,
            embedded_records=embedded_records,
            missing_records=missing_records,
            coverage_percent=round(coverage_percent, 1),
        )

    async def get_catalog_stats(self) -> CatalogStatsResponse:
        """Return catalog statistics: counts, storage, breakdowns."""
        db = self.db

        # Total datasets
        result = await db.execute(select(func.count()).select_from(Dataset))
        total_datasets = result.scalar_one()

        # Recent additions (last 30 days)
        result = await db.execute(
            select(func.count())
            .select_from(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .where(Record.created_at >= func.now() - text("interval '30 days'"))
        )
        recent_additions = result.scalar_one()

        # Storage usage
        total_storage_bytes: int | None = None
        try:
            async with db.begin_nested():
                result = await db.execute(
                    text(
                        "SELECT COALESCE(SUM(pg_total_relation_size('data.' || d.table_name)), 0) "
                        "FROM catalog.datasets d "
                        "WHERE EXISTS ("
                        "  SELECT 1 FROM information_schema.tables t "
                        "  WHERE t.table_schema = 'data' AND t.table_name = d.table_name"
                        ")"
                    )
                )
                total_storage_bytes = result.scalar_one()
        except Exception:
            logger.warning("Failed to compute storage usage", exc_info=True)
            total_storage_bytes = None

        # Datasets by geometry type
        result = await db.execute(
            select(Dataset.geometry_type, func.count())
            .where(Dataset.geometry_type.is_not(None))
            .group_by(Dataset.geometry_type)
        )
        datasets_by_geometry_type = {row[0]: row[1] for row in result.all()}

        # Datasets by visibility
        result = await db.execute(
            select(Record.visibility, func.count())
            .select_from(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .group_by(Record.visibility)
        )
        datasets_by_visibility = {row[0]: row[1] for row in result.all()}

        # Users by status
        result = await db.execute(
            select(User.status, func.count()).group_by(User.status)
        )
        users_by_status = {row[0]: row[1] for row in result.all()}
        total_users = sum(users_by_status.values())

        return CatalogStatsResponse(
            total_datasets=total_datasets,
            recent_additions=recent_additions,
            total_storage_bytes=total_storage_bytes,
            datasets_by_geometry_type=datasets_by_geometry_type,
            datasets_by_visibility=datasets_by_visibility,
            users_by_status=users_by_status,
            total_users=total_users,
        )
