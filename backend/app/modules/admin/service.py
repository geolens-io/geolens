"""Admin service: user CRUD, role assignment, and catalog stats."""

import uuid

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import (
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    UserUpdate,
)
from app.modules.auth.models import ApiKey, Role, User, UserRole
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.providers.local import hash_password
from app.modules.catalog.datasets.domain.models import Dataset, Record

logger = structlog.stdlib.get_logger(__name__)


class AdminService:
    """Handles admin-level user management operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_other_admin_count(self, exclude_user_id: uuid.UUID) -> int:
        """Count admin users excluding the given user_id."""
        result = await self.db.execute(
            select(func.count())
            .select_from(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .where(Role.name == "admin", UserRole.user_id != exclude_user_id)
        )
        return result.scalar() or 0

    async def _ensure_not_last_admin(self, user: User, action: str = "modify") -> None:
        """Raise ValueError if this is the last admin user."""
        if "admin" not in {r.name for r in user.roles}:
            return
        if await self._get_other_admin_count(exclude_user_id=user.id) == 0:
            raise ValueError(f"Cannot {action} the last admin user")

    async def _ensure_unique_user_field(
        self,
        field,
        value: str,
        error_msg: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise ValueError if a User row exists with field == value (case-insensitive).

        Used for username/email uniqueness checks. Pass exclude_id when updating
        an existing user to exclude that row from the check.
        """
        stmt = select(User).where(func.lower(field) == func.lower(value))
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if (await self.db.execute(stmt)).scalar_one_or_none() is not None:
            raise ValueError(error_msg)

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
        await self._ensure_unique_user_field(
            User.username, username, "Username already taken"
        )
        if email is not None:
            await self._ensure_unique_user_field(
                User.email, email, "Email already registered"
            )

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
            await self._ensure_unique_user_field(
                User.email,
                updates.email,
                "Email already registered",
                exclude_id=user_id,
            )
            user.email = updates.email

        if updates.is_active is not None:
            if updates.is_active is False:
                await self._ensure_not_last_admin(user, "deactivate")
            user.is_active = updates.is_active

        if updates.role is not None:
            await self._update_user_role(user, updates.role)

        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def _update_user_role(self, user: User, new_role_name: str) -> None:
        """Replace a user's role with new_role_name in the current transaction.

        Raises ValueError if the new role doesn't exist or if this would demote
        the sole admin.
        """
        role_result = await self.db.execute(
            select(Role).where(Role.name == new_role_name)
        )
        new_role = role_result.scalar_one_or_none()
        if new_role is None:
            raise ValueError(f"Role '{new_role_name}' not found")

        # Last-admin guard: prevent demoting the sole admin
        if (
            "admin" in {r.name for r in user.roles}
            and new_role_name != "admin"
            and await self._get_other_admin_count(exclude_user_id=user.id) == 0
        ):
            raise ValueError("Cannot demote the last admin user")

        await self.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        self.db.add(UserRole(user_id=user.id, role_id=new_role.id))

    async def convert_saml_user_to_local(
        self, user_id: uuid.UUID, password: str
    ) -> tuple[User, str]:
        """Convert a SAML-authenticated user to local-password (Phase 221 LIFECYCLE-06).

        In a single (uncommitted) DB transaction:
          1. Load the user; raise ValueError("User not found") if absent.
          2. Validate user.auth_provider == "oauth"; otherwise raise ValueError
             (router maps to 422).
          3. Find a SAML linkage (oauth_accounts row joined to oauth_providers
             where provider_type='saml'); raise ValueError if absent.
          4. Set user.password_hash = hash_password(password).
          5. Flip user.auth_provider from 'oauth' to 'local' (chk_users_auth_provider
             CHECK admits 'local').
          6. DELETE the SAML oauth_accounts row (clean break per D-04 -- the
             oauth_providers row stays; other users may still link to it).

        Returns (user, provider_slug). The router uses provider_slug to populate
        the audit-log details field. The router (NOT this method) writes the
        audit_log row and commits the transaction (per D-05).

        Per D-06: users.id is never updated; every FK referencing it is preserved
        by virtue of the row not moving.
        Per D-07: user_roles, api_keys, share_tokens, audit_logs, last_login_at
        are never touched.
        """
        # 1. Load user
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        # 2. Validate user is OAuth-authenticated
        if user.auth_provider != "oauth":
            raise ValueError(
                f"User auth_provider is '{user.auth_provider}', not 'oauth' "
                "-- conversion only applies to OAuth/SAML-authenticated users"
            )

        # 3. Find a SAML linkage for this user
        saml_link_stmt = (
            select(OAuthAccount, OAuthProvider.slug)
            .join(OAuthProvider, OAuthAccount.provider_id == OAuthProvider.id)
            .where(
                OAuthAccount.user_id == user_id,
                OAuthProvider.provider_type == "saml",
            )
        )
        link_row = (await self.db.execute(saml_link_stmt)).first()
        if link_row is None:
            raise ValueError(
                "User has no SAML provider linkage -- not a SAML-authenticated user"
            )
        saml_account, provider_slug = link_row

        # 4. Set password hash
        user.password_hash = hash_password(password)

        # 5. Flip auth_provider (chk_users_auth_provider admits 'local')
        user.auth_provider = "local"

        # 6. Delete the SAML linkage row (clean break per D-04). Scoped by id so
        #    only THIS user's SAML linkage is deleted -- other users' linkages
        #    AND this user's non-SAML linkages (multi-IdP edge case) are preserved.
        await self.db.execute(
            delete(OAuthAccount).where(OAuthAccount.id == saml_account.id)
        )

        await self.db.flush()
        await self.db.refresh(user)
        return user, provider_slug

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
        filters = []
        if status == "deactivated":
            filters.append(
                (User.status == "active") & (User.is_active == False)  # noqa: E712
            )
        elif status is not None:
            filters.append(User.status == status)
        if search is not None:
            pattern = f"%{search}%"
            filters.append(User.username.ilike(pattern) | User.email.ilike(pattern))

        count_query = select(func.count()).select_from(User).where(*filters)
        list_query = select(User).where(*filters).order_by(User.created_at)

        total = (await self.db.execute(count_query)).scalar() or 0
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

    async def delete_user(self, user_id: uuid.UUID, current_user_id: uuid.UUID) -> str:
        """Hard-delete a user. Returns the deleted username for audit logging.

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

        username = user.username

        # Delete related records that have CASCADE or need explicit cleanup
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self.db.execute(delete(ApiKey).where(ApiKey.user_id == user_id))

        # Hard delete the user (FK SET NULL handles audit_logs, datasets, ingest_jobs)
        await self.db.delete(user)
        await self.db.flush()
        return username

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
        from app.modules.auth.models import User as UserModel
        from app.platform.jobs.models import IngestJob

        filters = []
        if status is not None:
            filters.append(IngestJob.status == status)
        if user_id is not None:
            filters.append(IngestJob.created_by == user_id)
        if search is not None:
            filters.append(IngestJob.source_filename.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(IngestJob).where(*filters)
        total = (await self.db.execute(count_stmt)).scalar_one()

        list_stmt = (
            select(IngestJob, UserModel.username)
            .outerjoin(UserModel, IngestJob.created_by == UserModel.id)
            .where(*filters)
            .order_by(IngestJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = (await self.db.execute(list_stmt)).all()

        return rows, total

    async def revoke_share_token_with_cascade(
        self, token_id: uuid.UUID
    ) -> tuple[uuid.UUID, uuid.UUID, int] | None:
        """Revoke a share token and cascade-revoke all active embed tokens for the map.

        Returns (token_id, map_id, cascade_embed_count) on success; None if the
        share token doesn't exist (caller maps to 404). Caller is responsible
        for committing the transaction and writing the audit log.
        """
        from app.modules.catalog.maps.service import revoke_share_token
        from app.modules.embed_tokens.models import EmbedToken
        from app.modules.embed_tokens.service import bulk_revoke_embed_tokens

        token_obj = await revoke_share_token(self.db, token_id)
        if token_obj is None:
            return None

        result = await self.db.execute(
            select(EmbedToken.id).where(
                EmbedToken.map_id == token_obj.map_id,
                EmbedToken.is_active.is_(True),
            )
        )
        embed_ids = [row[0] for row in result.all()]
        if embed_ids:
            await bulk_revoke_embed_tokens(self.db, embed_ids)

        return token_obj.id, token_obj.map_id, len(embed_ids)

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
        except Exception:  # broad: pgvector table may be missing or DB unavailable; degrade to zeros for admin UI
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
        except Exception:  # broad: pg_total_relation_size can fail on missing data.* tables; degrade to None
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
