"""Admin service: user CRUD, role assignment, and catalog stats."""

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import delete, func, nulls_last, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.admin.schemas import (
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    UserUpdate,
)
from app.modules.auth.models import ApiKey, Role, User, UserRole
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.providers.local import hash_password
from app.modules.auth.service import AuthService
from app.core.text import escape_ilike

logger = structlog.stdlib.get_logger(__name__)

# Serialize every operation that can reduce the set of viable administrators.
# This is deliberately an application-wide PostgreSQL advisory transaction lock:
# locking individual User rows is insufficient when two admins concurrently
# deactivate each other (each operation targets a different row).
_ADMIN_LIFECYCLE_LOCK_KEY = 0x47454F4C41444D49  # "GEOLADMI"

# Inner half of the user-list sort allowlist (outer: UserSortField in
# schemas.py). A sort key is only ever a dict lookup, so an unmapped value
# cannot reach SQL as text; list_users raises rather than falling back silently.
USER_SORT_COLUMNS: dict[str, InstrumentedAttribute] = {
    "username": User.username,
    "email": User.email,
    "status": User.status,
    "last_login_at": User.last_login_at,
    "created_at": User.created_at,
}

# Nullable members of USER_SORT_COLUMNS. Postgres defaults NULLs to the end on
# ASC and the front on DESC, which would float never-logged-in accounts to the
# top of a descending "Last Login" sort. Pin them last in both directions.
_NULLABLE_USER_SORT_COLUMNS = frozenset({"email", "last_login_at"})

# Inner half of the job-list sort allowlist (outer: JobSortField in
# schemas.py). A function, not a module constant, because IngestJob is
# imported lazily here; hoisting it would put a platform.jobs import in
# every importer of this module.
_NULLABLE_JOB_SORT_COLUMNS = frozenset({"source_filename", "username", "duration"})


def _job_sort_columns() -> dict[str, Any]:
    """Map an allowlisted job sort key to the expression that orders it."""
    from app.platform.jobs.models import IngestJob

    return {
        "created_at": IngestJob.created_at,
        "source_filename": IngestJob.source_filename,
        "status": IngestJob.status,
        # The list query already outer-joins users for the displayed username,
        # so ordering by it costs nothing extra.
        "username": User.username,
        # Column expression for the UI's Duration cell: NULL for exactly the
        # rows that render "-", so ordering and the cell agree without a
        # second rule. Pinned NULLS LAST below (_NULLABLE_JOB_SORT_COLUMNS).
        "duration": IngestJob.completed_at - IngestJob.started_at,
    }


class PendingUserMutationError(ValueError):
    """Raised when generic user PATCH attempts an approval-only mutation."""


class PendingUserTransitionConflict(ValueError):
    """Raised when a pending-user decision has already been made."""


async def _get_total_storage_bytes(db: AsyncSession, dataset_model: type) -> int:
    """Measure visible dataset tables without mixing catalog and data roles.

    In hosted mode, catalog rows are visible to the runtime role through RLS,
    while physical table metadata is visible only after the statement hook
    selects the active tenant's reader role. Keeping those operations in two
    statements lets each execute under its least-privilege role.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var

    data_schema = tenant_data_schema(current_tenant_var.get())
    table_result = await db.execute(select(dataset_model.table_name))
    table_names = list(table_result.scalars().all())
    if not table_names:
        return 0

    async with db.begin_nested():
        result = await db.execute(
            text(
                "SELECT COALESCE(SUM(pg_total_relation_size("
                "  to_regclass(format('%I.%I', :schema, names.table_name))"
                ")), 0) "
                "FROM unnest(CAST(:table_names AS text[])) AS names(table_name)"
            ).bindparams(schema=data_schema, table_names=table_names)
        )
        return result.scalar_one()


@dataclass(frozen=True)
class IdentityRoleOutcome:
    """What ``set_role_from_identity_provider`` did.

    fix(#1778): three states, since the caller audits each differently:

    * ``applied=False`` -- the last-admin rule refused the demotion.
    * ``applied=True, changed=False`` -- role already matched; nothing to
      record (a second concurrent callback lands here once it gets the lock).
    * ``applied=True, changed=True`` -- role moved; ``previous_roles`` says
      from where, always read UNDER the advisory lock so it reflects the
      actual starting state.
    """

    applied: bool
    changed: bool
    previous_roles: list[str]


class AdminService:
    """Handles admin-level user management operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _lock_admin_lifecycle(self) -> None:
        """Acquire the transaction-scoped global admin-lifecycle lock."""
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _ADMIN_LIFECYCLE_LOCK_KEY},
        )

    async def _get_other_admin_count(self, exclude_user_id: uuid.UUID) -> int:
        """Count other *viable* admins that can still authenticate."""
        result = await self.db.execute(
            select(func.count(func.distinct(UserRole.user_id)))
            .select_from(UserRole)
            .join(User, UserRole.user_id == User.id)
            .join(Role, UserRole.role_id == Role.id)
            .where(
                Role.name == "admin",
                UserRole.user_id != exclude_user_id,
                User.status == "active",
                User.is_active == True,  # noqa: E712
            )
        )
        return result.scalar() or 0

    @staticmethod
    def _is_viable_admin(user: User) -> bool:
        return (
            user.status == "active"
            and user.is_active
            and "admin" in {role.name for role in user.roles}
        )

    @staticmethod
    def _user_audit_snapshot(user: User) -> dict[str, Any]:
        """Return the non-secret lifecycle fields used by user.update audits."""
        return {
            "email": user.email,
            "is_active": user.is_active,
            "status": user.status,
            "roles": sorted(role.name for role in user.roles),
        }

    async def _ensure_not_last_admin(
        self,
        user: User,
        action: str = "modify",
        *,
        lock_held: bool = False,
    ) -> None:
        """Raise if removing this user's viability would leave no active admin.

        The advisory lock spans the caller's transaction, so a concurrent
        reducer cannot pass the same count check against a stale snapshot.
        """
        if not lock_held:
            await self._lock_admin_lifecycle()
            await self.db.refresh(user, attribute_names=["roles"])
        if not self._is_viable_admin(user):
            return
        if await self._get_other_admin_count(exclude_user_id=user.id) == 0:
            raise ValueError(f"Cannot {action} the last admin user")

    async def _get_lifecycle_user(self, user_id: uuid.UUID) -> User:
        """Lock the invariant and return the latest target user row."""
        await self._lock_admin_lifecycle()
        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        return user

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

        HARDEN-04: the role-existence check runs BEFORE the User row is added
        or flushed, for a readable error rather than the FK backstop alone.
        The TOCTOU window (role deleted between check and insert) is accepted
        -- the FK constraint catches it.
        """
        await self._ensure_unique_user_field(
            User.username, username, "Username already taken"
        )
        if email is not None:
            await self._ensure_unique_user_field(
                User.email, email, "Email already registered"
            )

        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found")

        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email,
            status="active",
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()

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
        user = await self._get_lifecycle_user(user_id)

        if user.status == "pending":
            raise PendingUserTransitionConflict(
                "Pending users must be approved or rejected before deactivation"
            )

        if current_user_id is not None and user_id == current_user_id:
            raise ValueError("Cannot deactivate your own account")

        await self._ensure_not_last_admin(user, "deactivate", lock_held=True)

        user.status = "deactivated"
        user.is_active = False
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def reset_user_password(self, user_id: uuid.UUID, password: str) -> User:
        """Set another account's password (feat(#1715)), revoking its credentials.

        Mirrors change_password's aftermath: revoke_all_tokens with
        bump_key_epoch=True, so every outstanding JWT, refresh row and API key
        the account holds stops resolving.

        commit=False folds the revocation into the caller's transaction, so the
        new hash, revocation and audit row land together or not at all.

        Identity-provider accounts have no local password to replace; raises
        rather than silently minting one (router maps to 422).
        _get_lifecycle_user gives the shared 404 plus the row lock that
        serializes against a concurrent deactivate/delete.
        """
        user = await self._get_lifecycle_user(user_id)
        if user.auth_provider != "local":
            raise ValueError(
                f"User auth_provider is '{user.auth_provider}', not 'local' "
                "-- this account signs in through an identity provider"
            )

        user.password_hash = hash_password(password)
        await AuthService(self.db).revoke_all_tokens(
            user_id, commit=False, bump_key_epoch=True
        )
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update_user(
        self,
        user_id: uuid.UUID,
        updates: UserUpdate,
        current_user_id: uuid.UUID | None = None,
    ) -> User:
        """Update a user's fields and/or role.

        Raises ValueError if user not found or role not found.
        """
        user, _, _ = await self.update_user_with_snapshot(
            user_id, updates, current_user_id=current_user_id
        )
        return user

    async def update_user_with_snapshot(
        self,
        user_id: uuid.UUID,
        updates: UserUpdate,
        *,
        current_user_id: uuid.UUID | None = None,
    ) -> tuple[User, dict[str, Any], dict[str, Any]]:
        """Update a user and return stable before/after audit snapshots."""
        user = await self._get_lifecycle_user(user_id)
        before = self._user_audit_snapshot(user)

        target_status = updates.status
        if target_status is None and updates.is_active is not None:
            # Backward-compatible mapping for existing API clients.
            target_status = "active" if updates.is_active else "deactivated"

        if user.status == "pending" and (
            target_status is not None or updates.role is not None
        ):
            raise PendingUserMutationError(
                "Pending users must be approved or rejected; role and status "
                "cannot be changed via PATCH"
            )

        if (
            current_user_id is not None
            and user_id == current_user_id
            and target_status is not None
            and target_status != "active"
        ):
            raise ValueError("Cannot deactivate or suspend your own account")

        will_remove_viability = self._is_viable_admin(user) and (
            (target_status is not None and target_status != "active")
            or (updates.role is not None and updates.role != "admin")
        )
        if will_remove_viability:
            action = (
                "demote"
                if updates.role not in (None, "admin")
                else {
                    "deactivated": "deactivate",
                    "suspended": "suspend",
                }.get(target_status or "", "modify")
            )
            await self._ensure_not_last_admin(user, action, lock_held=True)

        # Apply non-None scalar fields
        if updates.email is not None:
            await self._ensure_unique_user_field(
                User.email,
                updates.email,
                "Email already registered",
                exclude_id=user_id,
            )
            user.email = updates.email

        if target_status is not None:
            user.status = target_status
            user.is_active = target_status == "active"

        if updates.role is not None:
            await self._update_user_role(
                user, updates.role, lock_held=True, viability_checked=True
            )

        await self.db.flush()
        await self.db.refresh(user, attribute_names=["roles"])
        after = self._user_audit_snapshot(user)
        return user, before, after

    async def _update_user_role(
        self,
        user: User,
        new_role_name: str,
        *,
        lock_held: bool = False,
        viability_checked: bool = False,
    ) -> bool:
        """Replace a user's role with new_role_name in the current transaction.

        Returns whether the roles actually CHANGED (fix(#1778)): the caller
        needs to tell "applied" from "was already correct", since an
        IdP-driven caller only emits an audit event for a real change.

        Raises ValueError if the new role doesn't exist or if this would demote
        the sole admin.
        """
        role_result = await self.db.execute(
            select(Role).where(Role.name == new_role_name)
        )
        new_role = role_result.scalar_one_or_none()
        if new_role is None:
            raise ValueError(f"Role '{new_role_name}' not found")

        # fix(#821): an idempotent resubmission of the user's current role
        # (e.g. a reconciliation-tool PATCH) is not a security event — skip
        # the delete/recreate and the key_epoch bump so API keys survive.
        # Queried explicitly rather than via user.roles to avoid depending on
        # relationship load state.
        current_role_names = set(
            (
                await self.db.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user.id)
                )
            ).scalars()
        )
        if current_role_names == {new_role_name}:
            return False

        if new_role_name != "admin" and not viability_checked:
            await self._ensure_not_last_admin(user, "demote", lock_held=lock_held)

        await self.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        self.db.add(UserRole(user_id=user.id, role_id=new_role.id))

        # fix(#821): bump key_epoch so API keys minted under the old role stop
        # resolving — applies to promotion too, since a key must not silently
        # change privilege level. token_version is NOT bumped: JWTs are
        # short-lived and role checks read live DB roles per request.
        await self.db.execute(
            update(User).where(User.id == user.id).values(key_epoch=User.key_epoch + 1)
        )
        return True

    async def set_role_from_identity_provider(
        self, user: User, role_name: str
    ) -> IdentityRoleOutcome:
        """Apply an IdP-mapped role. False when the last-admin rule refused it.

        fix(#1778): the public seam for two invariants OAuth reconciliation
        (``_reconcile_mapped_role`` in modules/auth/oauth/service.py) must not
        skip: the last-admin rule, and the ``key_epoch`` bump (#821) so a role
        change actually revokes stale-privilege API keys. Calls the same
        ``_ensure_not_last_admin``/``_update_user_role`` the admin router uses.
        A refusal is not an error here -- login continues with the role
        unchanged and the caller records why.

        The advisory lock is taken here (call only when a change is needed;
        the caller compares the current role first) and covers BOTH branches,
        including promotion: two concurrent OAuth callbacks for the same
        account can otherwise both run ``_update_user_role`` unserialized,
        colliding on ``user_roles``'s ``(user_id, role_id)`` primary key. Under
        the lock, ``_update_user_role``'s idempotency check makes the second
        caller's re-read a no-op instead. One lock for both branches, since
        demotion needs the global one anyway (last-admin count is fleet-wide).

        Returns an outcome, not a bare bool, with ``previous_roles`` read
        UNDER the lock -- reading it before the lock let two racing callbacks
        both emit an `oauth.role.changed` event for the same transition, the
        loser's snapshot stale by the time it was recorded.
        """
        await self._lock_admin_lifecycle()
        await self.db.refresh(user, attribute_names=["roles"])
        # Read under the lock: anything captured before waiting for it describes
        # a state another caller may already have replaced.
        previous_roles = sorted(role.name for role in user.roles)

        if role_name == "admin":
            # A promotion cannot threaten the last-admin invariant, so it skips
            # the check but not the lock.
            changed = await self._update_user_role(user, role_name, lock_held=True)
            return IdentityRoleOutcome(True, changed, previous_roles)

        try:
            await self._ensure_not_last_admin(user, "demote", lock_held=True)
        except ValueError:
            # The only ValueError _ensure_not_last_admin raises is the refusal
            # itself, and it is a refusal here rather than a failure.
            return IdentityRoleOutcome(False, False, previous_roles)
        changed = await self._update_user_role(
            user, role_name, lock_held=True, viability_checked=True
        )
        return IdentityRoleOutcome(True, changed, previous_roles)

    async def convert_saml_user_to_local(
        self, user_id: uuid.UUID, password: str
    ) -> tuple[User, str]:
        """Convert a SAML-authenticated user to local-password (Phase 221 LIFECYCLE-06).

        In one (uncommitted) transaction:
          1. Load the user; raise ValueError("User not found") if absent.
          2. Validate user.auth_provider == "oauth"; otherwise raise ValueError
             (router maps to 422).
          3. Find a SAML linkage (oauth_accounts joined to oauth_providers where
             provider_type='saml'); raise ValueError if absent.
          4. Set user.password_hash = hash_password(password).
          5. Flip user.auth_provider from 'oauth' to 'local'.
          6. DELETE the SAML oauth_accounts row (clean break, D-04 -- the
             oauth_providers row stays; other users may still link to it).
          7. revoke_all_tokens(commit=False, bump_key_epoch=True) so no
             SAML-era credential survives.

        Returns (user, provider_slug); the router uses provider_slug for the
        audit-log details and writes/commits the audit row itself (D-05).

        Per D-06/D-07: users.id, and user_roles/api_keys/share_tokens/audit_logs/
        last_login_at, are never touched.
        """
        # fix(#1715): FOR UPDATE, matching the reset and the login -- this
        # rotates credentials and must not read/decide/write from a snapshot
        # another writer can invalidate underneath it.
        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        if user.auth_provider != "oauth":
            raise ValueError(
                f"User auth_provider is '{user.auth_provider}', not 'oauth' "
                "-- conversion only applies to OAuth/SAML-authenticated users"
            )

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

        user.password_hash = hash_password(password)

        # chk_users_auth_provider admits 'local'.
        user.auth_provider = "local"

        # Scoped by id: only THIS user's SAML linkage is deleted -- other
        # users' linkages AND this user's non-SAML linkages are preserved.
        await self.db.execute(
            delete(OAuthAccount).where(OAuthAccount.id == saml_account.id)
        )

        # SEC-S15 CR-02: forces re-authentication rather than leaving an
        # outstanding SAML JWT valid until natural expiry, and SAML-era
        # refresh tokens unusable afterwards. bump_key_epoch=True (fix(#821))
        # also stops pre-conversion API keys.
        #
        # fix(#1455): one call replacing two inline UPDATEs that had drifted;
        # commit=False folds it into the caller's transaction.
        await AuthService(self.db).revoke_all_tokens(
            user_id, commit=False, bump_key_epoch=True
        )

        await self.db.flush()
        await self.db.refresh(user)
        return user, provider_slug

    @staticmethod
    def _user_ordering(sort: str, order: str) -> list[Any]:
        """Resolve a sort key/direction pair to ORDER BY clauses.

        Raises ValueError for anything outside the allowlist, so a bad key
        fails loudly here instead of silently degrading to a default order.
        """
        column = USER_SORT_COLUMNS.get(sort)
        if column is None:
            raise ValueError(f"Unsupported sort field: {sort!r}")
        if order not in ("asc", "desc"):
            raise ValueError(f"Unsupported sort order: {order!r}")

        clause = column.desc() if order == "desc" else column.asc()
        if sort in _NULLABLE_USER_SORT_COLUMNS:
            clause = nulls_last(clause)

        # Every sortable column except created_at admits duplicates, and OFFSET
        # paging over a non-unique key lets Postgres return a row twice (or skip
        # it) across page boundaries. The id tiebreak makes the order total.
        return [clause, User.id]

    async def list_users(
        self,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
        role: str | None = None,
        search: str | None = None,
        sort: str = "created_at",
        order: str = "asc",
    ) -> tuple[list[User], int]:
        """List users with pagination and optional status, role, and search filters.

        `sort` must be a key of USER_SORT_COLUMNS and `order` one of
        asc/desc; anything else raises ValueError. The default ordering
        (created_at ascending) is the historical one and is unchanged.

        Returns (users, total_count).
        """
        filters = []
        if status is not None:
            filters.append(User.status == status)
        if role is not None:
            filters.append(User.roles.any(Role.name == role))
        if search is not None:
            # T-2/T-1: normalize BOTH column AND pattern with
            # lower(catalog.immutable_unaccent(...)) to match the trigram GIN
            # indexes (ix_users_username_trgm, ix_users_email_trgm) and make
            # search accent-insensitive ("José" must itself be unaccented).
            # escape_ilike() keeps %, _, \ literal.
            pattern = func.concat(
                "%", func.catalog.immutable_unaccent(escape_ilike(search).lower()), "%"
            )

            filters.append(
                func.lower(func.catalog.immutable_unaccent(User.username)).like(
                    pattern, escape="\\"
                )
                | func.lower(func.catalog.immutable_unaccent(User.email)).like(
                    pattern, escape="\\"
                )
            )

        count_query = select(func.count()).select_from(User).where(*filters)
        list_query = (
            select(User).where(*filters).order_by(*self._user_ordering(sort, order))
        )

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
        """Atomically approve a pending user and replace its assigned role.

        The row lock serializes approve/approve and approve/reject decisions. A
        concurrent loser observes a transition conflict instead of appending a
        second role or deleting an account that was just approved.

        Raises PendingUserTransitionConflict if an existing account has
        already left pending state, or ValueError if the user or requested
        role does not exist.
        """
        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found")

        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        if user.status != "pending":
            raise PendingUserTransitionConflict(
                "Pending user approval is no longer available"
            )

        user.status = "active"
        user.is_active = True

        # fix(#821): approval assigns the account's authority, so bump
        # key_epoch — any key that existed while pending (legacy/manual rows;
        # minting for non-active users is now refused) must not wake up with
        # the approved role's privileges. Race-free: the row is locked above.
        user.key_epoch += 1

        # A pending account should not normally own a role, but legacy/manual
        # rows may. Replace the complete assignment so the approved role is the
        # only authority the newly active account receives.
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        await self.db.flush()
        await self.db.refresh(user, attribute_names=["roles"])
        return user

    async def reject_user(self, user_id: uuid.UUID) -> None:
        """Atomically reject a pending user by hard-deleting them.

        Raises PendingUserTransitionConflict if an existing account has
        already left pending state, or ValueError if the user does not exist.
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        if user.status != "pending":
            raise PendingUserTransitionConflict(
                "Pending user rejection is no longer available"
            )

        await self.db.delete(user)
        await self.db.flush()

    async def delete_user(self, user_id: uuid.UUID, current_user_id: uuid.UUID) -> str:
        """Hard-delete a user. Returns the deleted username for audit logging.

        Raises ValueError for self-deletion, last-admin deletion, or not found.
        FK SET NULL handles audit_logs, datasets, ingest_jobs automatically.
        """
        user = await self._get_lifecycle_user(user_id)

        if user_id == current_user_id:
            raise ValueError("Cannot delete your own account")

        await self._ensure_not_last_admin(user, "delete", lock_held=True)

        username = user.username

        # Delete related records that have CASCADE or need explicit cleanup
        await self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self.db.execute(delete(ApiKey).where(ApiKey.user_id == user_id))

        # Hard delete the user (FK SET NULL handles audit_logs, datasets, ingest_jobs)
        await self.db.delete(user)
        await self.db.flush()
        return username

    @staticmethod
    def _job_ordering(sort: str, order: str) -> list[Any]:
        """Resolve a job sort key/direction pair to ORDER BY clauses.

        Raises ValueError outside the allowlist rather than degrading to the
        default order, so a typo'd key fails loudly instead of silently
        serving a differently-ordered page.
        """
        from app.platform.jobs.models import IngestJob

        column = _job_sort_columns().get(sort)
        if column is None:
            raise ValueError(f"Unsupported sort field: {sort!r}")
        if order not in ("asc", "desc"):
            raise ValueError(f"Unsupported sort order: {order!r}")

        clause = column.desc() if order == "desc" else column.asc()
        if sort in _NULLABLE_JOB_SORT_COLUMNS:
            clause = nulls_last(clause)

        # Every sortable job column admits duplicates — created_at included,
        # since a fan-out enqueues its children in one transaction. OFFSET
        # paging over a non-unique key lets Postgres return a row on two
        # consecutive pages; the id tiebreak makes the order total.
        return [clause, IngestJob.id]

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        user_id: uuid.UUID | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 50,
        sort: str = "created_at",
        order: str = "desc",
    ) -> tuple[list, int]:
        """List ingestion jobs with optional filters. Returns (rows, total).

        `sort` must be a key of _job_sort_columns() and `order` one of
        asc/desc; anything else raises ValueError. The default ordering
        (created_at descending) is the historical one and is unchanged.
        """
        from app.modules.auth.models import User as UserModel
        from app.platform.jobs.models import IngestJob

        filters = []
        if status is not None:
            filters.append(IngestJob.status == status)
        if user_id is not None:
            filters.append(IngestJob.created_by == user_id)
        if search is not None:
            # escape_ilike() keeps %, _, \ literal (the bare f"%{search}%"
            # previously leaked wildcards); escape="\\" matches the sibling
            # call sites (list_users above, maps/audit/embed-token searches).
            filters.append(
                IngestJob.source_filename.ilike(
                    f"%{escape_ilike(search)}%", escape="\\"
                )
            )

        count_stmt = select(func.count()).select_from(IngestJob).where(*filters)
        total = (await self.db.execute(count_stmt)).scalar_one()

        list_stmt = (
            select(IngestJob, UserModel.username)
            .outerjoin(UserModel, IngestJob.created_by == UserModel.id)
            .where(*filters)
            .order_by(*self._job_ordering(sort, order))
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
        """Return embedding coverage statistics for the ACTIVE embedding model.

        fix(#1503): scoped to the current model name — `record_embeddings` is
        keyed `(record_id, model_name)`, and semantic search only reads rows
        matching the active model. Counting every row regardless of model
        showed 100% coverage after a model swap while search matched nothing.
        When the active model can't be resolved, the sentinel name matches no
        row, so coverage reads 0 -- deliberate, since search is equally unusable.

        fix(#1546): same argument, one value out -- a row with the active model
        name but another CONFIGURATION's stamp is a different vector space, so
        counting it would show the same false-healthy coverage.

        The FILTER below is the SQL spelling of
        `RecordEmbedding.usable_by_config` (also used by the non-force backfill
        and semantic search); `test_embedding_config_stamp_1546.py` asserts the
        two spellings agree.
        """
        from app.processing.embeddings.helpers import (
            resolve_embedding_config_fingerprint,
            resolve_embedding_model_name,
        )

        try:
            model_name = await resolve_embedding_model_name(self.db)
            config_fingerprint = await resolve_embedding_config_fingerprint(
                self.db, model_name=model_name
            )
            result = await self.db.execute(
                text(
                    "SELECT COUNT(DISTINCT visible_record.id) AS total_records, "
                    "COUNT(DISTINCT visible_record.id) "
                    "FILTER (WHERE embedding.model_name = :model_name "
                    "AND (embedding.config_fingerprint IS NULL "
                    "OR embedding.config_fingerprint = :config_fingerprint)) "
                    "AS embedded_records, "
                    "COUNT(DISTINCT visible_record.id) "
                    "FILTER (WHERE embedding.record_id IS NOT NULL) "
                    "AS any_model_records "
                    "FROM catalog.records AS visible_record "
                    "LEFT JOIN catalog.record_embeddings AS embedding "
                    "ON embedding.record_id = visible_record.id"
                ),
                {"model_name": model_name, "config_fingerprint": config_fingerprint},
            )
            total_records, embedded_records, any_model_records = result.one()
        except Exception:  # broad: pgvector table may be missing or DB unavailable; degrade to zeros for admin UI
            logger.warning("Failed to query embedding stats", exc_info=True)
            return EmbeddingStatsResponse(
                total_records=0,
                embedded_records=0,
                missing_records=0,
                stale_records=0,
                coverage_percent=0.0,
            )

        missing_records = total_records - embedded_records
        # Records carrying vectors, but none the active CONFIGURATION can use
        # (fix(#1546): "configuration", not "model"). fix(#1506): the
        # non-force backfill selects on "no active-model row" rather than "no
        # row at all", so Generate Missing re-embeds these without touching
        # records the current model already covers; superseded rows are left
        # in place (storage cost only, no longer counted as stale here).
        stale_records = any_model_records - embedded_records
        coverage_percent = (
            (embedded_records / total_records * 100) if total_records > 0 else 0.0
        )
        # Deliberately after the coverage query's own degrade-to-zeros exit: a
        # database that cannot answer the count above cannot answer this either,
        # and the panel keeps the reduced response it has always had.
        from app.modules.admin.backfill_jobs import collect_backfill_observability

        runs = await collect_backfill_observability(
            self.db, missing_records=missing_records, total_records=total_records
        )
        return EmbeddingStatsResponse(
            total_records=total_records,
            embedded_records=embedded_records,
            missing_records=missing_records,
            stale_records=stale_records,
            coverage_percent=round(coverage_percent, 1),
            **runs,
        )

    async def get_catalog_stats(self) -> CatalogStatsResponse:
        db = self.db
        from app.platform.extensions import get_processing_port

        port = get_processing_port()
        Dataset = port.get_dataset_orm_class()
        Record = port.get_record_orm_class()

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
            total_storage_bytes = await _get_total_storage_bytes(db, Dataset)
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
