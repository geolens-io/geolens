"""Auth service: JWT token creation, refresh tokens, and user registration."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import delete, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenancy import is_multi_tenant
from app.modules.auth.models import ApiKey, RefreshToken, Role, User, UserRole
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.providers.local import hash_password


class AuthService:
    """Handles JWT creation, user registration, and role queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_access_token(
        self,
        identity: AuthenticatedIdentity,
        expire_minutes: int | None = None,
        *,
        family_id: uuid.UUID | None = None,
    ) -> str:
        """Create a signed JWT for the given identity.

        SEC-S15 (Phase 1062-01): payload includes ``jti`` (unique per-token
        id) and ``token_version`` — a JWT whose token_version is behind the
        user's current value is rejected by get_current_user/get_optional_user,
        so logout and password-change revocations take effect immediately.
        """
        minutes = expire_minutes or settings.access_token_expire_minutes
        now = datetime.now(UTC)
        multi_tenant = is_multi_tenant()

        # Column-only select avoids a redundant full-row read when the User
        # row was already loaded by the caller; a safe extra query either way.
        if multi_tenant:
            result = await self.db.execute(
                select(User.token_version, User.tenant_id).where(
                    User.id == identity.user_id
                )
            )
            row = result.one_or_none()
            _raw_version = row.token_version if row is not None else None
            tenant_id = row.tenant_id if row is not None else None
        else:
            # Preserve the single-tenant query and token payload exactly. The
            # tenancy axis must remain inert for Community/self-hosted installs.
            result = await self.db.execute(
                select(User.token_version).where(User.id == identity.user_id)
            )
            _raw_version = result.scalar_one_or_none()
            tenant_id = None
        # WR-04: explicit None check rather than `or 1`, so a stored
        # token_version=0 isn't silently coerced to 1 (unreachable today, but
        # explicit intent beats relying on falsiness).
        token_version: int = _raw_version if _raw_version is not None else 1

        payload = {
            "sub": str(identity.user_id),
            "username": identity.username,
            "jti": uuid.uuid4().hex,
            "token_version": token_version,
            "exp": now + timedelta(minutes=minutes),
            "iat": now,
        }
        if family_id is not None:
            payload["sid"] = str(family_id)
        if multi_tenant:
            if tenant_id is None:
                raise ValueError(
                    "Cannot issue a multi-tenant access token without a tenant id"
                )
            payload["tid"] = str(tenant_id)
        return jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    def create_download_token(
        self,
        identity: AuthenticatedIdentity,
        dataset_id: uuid.UUID,
        expire_seconds: int = 120,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> str:
        """Create a download-scoped JWT for a single dataset.

        SEC-04/M-66: a JWT in a URL query parameter is far more leak-prone
        than a Bearer header (browser history, logs, accidental copy).
        ``typ='download'``, a dataset-scoped ``scope``, and a <=2-minute TTL
        bound the damage if the URL is exposed; the session JWT keeps working
        via the Authorization header. ``expire_seconds`` is silently capped
        at 120, never raised.
        """
        ttl = min(expire_seconds, 120)
        now = datetime.now(UTC)
        payload = {
            "sub": str(identity.user_id),
            "username": identity.username,
            "typ": "download",
            "scope": f"dataset:{dataset_id}",
            "exp": now + timedelta(seconds=ttl),
            "iat": now,
        }
        if is_multi_tenant():
            if tenant_id is None:
                raise ValueError(
                    "Cannot issue a multi-tenant download token without a tenant id"
                )
            payload["tid"] = str(tenant_id)
        return jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    def create_refresh_token(
        self,
        user_id: uuid.UUID,
        expire_days: int | None = None,
        *,
        family_id: uuid.UUID | None = None,
    ) -> str:
        """expire_days falls back to settings.refresh_token_expire_days if None."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        days = expire_days or settings.refresh_token_expire_days
        expires_at = datetime.now(UTC) + timedelta(days=days)
        refresh = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=expires_at,
        )
        self.db.add(refresh)
        return raw_token

    async def get_user_from_refresh_token(self, raw_token: str) -> "User | None":
        """Return the User linked to *raw_token* without revoking it.

        CR-01 (Phase 1236 Plan 03): used by the refresh handler to check the
        domain allowlist BEFORE the old token is revoked — callers must call
        rotate_refresh_token only after the check passes, so a rejected token
        stays usable (no silent revocation on block).

        Returns None if the token is missing, expired, revoked, the linked
        user doesn't exist, or the row predates the owner's revocation horizon.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken)
            .join(User, RefreshToken.user_id == User.id)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
                RefreshToken.expires_at > datetime.now(UTC),
                or_(
                    RefreshToken.rotated_at.is_(None),
                    RefreshToken.rotated_at
                    > datetime.now(UTC)
                    - timedelta(seconds=settings.refresh_rotation_grace_seconds),
                ),
                # fix(#1455): revocation horizon, checked at use time so it
                # covers rows revoke_all_tokens couldn't see when it ran (DB
                # clock on both sides, so skew-free).
                or_(
                    User.sessions_revoked_at.is_(None),
                    RefreshToken.created_at > User.sessions_revoked_at,
                ),
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            return None
        user_result = await self.db.execute(
            select(User).where(User.id == stored.user_id)
        )
        return user_result.scalar_one_or_none()

    async def rotate_refresh_token(
        self,
        raw_token: str,
        expire_minutes: int | None = None,
        expire_days: int | None = None,
    ) -> tuple[str, str]:
        """Validate refresh token, retire it, issue new access + refresh pair.

        Concurrent callers inside the rotation grace window receive their own
        valid successors in the same family. Reuse after grace revokes that
        family, until the presented token reaches its original expiry.

        Returns (new_access_token, new_refresh_token).
        Raises ValueError on invalid/expired/revoked token or inactive user.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken.user_id)
            .join(User, RefreshToken.user_id == User.id)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
                RefreshToken.expires_at > datetime.now(UTC),
                or_(
                    User.sessions_revoked_at.is_(None),
                    RefreshToken.created_at > User.sessions_revoked_at,
                ),
            )
        )
        user_id = result.scalar_one_or_none()
        if user_id is None:
            raise ValueError("Invalid or expired refresh token")

        # Every family mutation shares revoke-all's owner lock.
        # Re-read rows after waiting so a queued rotation cannot revive a family.
        user = (
            await self.db.execute(
                select(User)
                .where(User.id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if user is None or not user.is_active or user.status != "active":
            raise ValueError("User account is not active")
        stored = (
            await self.db.execute(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_hash)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            stored is None
            or stored.revoked
            or (
                user.sessions_revoked_at is not None
                and stored.created_at <= user.sessions_revoked_at
            )
        ):
            raise ValueError("Invalid or expired refresh token")

        now = datetime.now(UTC)
        grace = timedelta(seconds=settings.refresh_rotation_grace_seconds)
        if stored.expires_at <= now:
            raise ValueError("Invalid or expired refresh token")
        if stored.rotated_at is not None and now >= stored.rotated_at + grace:
            await self._revoke_family(user.id, stored.family_id)
            # The router returns 401; the revocation must survive its rollback.
            await self.db.commit()
            raise ValueError("Invalid or expired refresh token")
        if stored.rotated_at is None:
            stored.rotated_at = now

        identity = AuthenticatedIdentity(user_id=user.id, username=user.username)
        new_access = await self.create_access_token(
            identity, expire_minutes=expire_minutes, family_id=stored.family_id
        )
        new_refresh = self.create_refresh_token(
            user.id, expire_days=expire_days, family_id=stored.family_id
        )
        await self.cleanup_refresh_tokens()

        await self.db.commit()
        return new_access, new_refresh

    async def cleanup_refresh_tokens(self) -> None:
        """Keep hashes through original expiry plus one day, even after rotation."""
        await self.db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < datetime.now(UTC) - timedelta(days=1),
                RefreshToken.user_id.in_(select(User.id)),
            )
        )

    async def _revoke_family(self, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
        """Caller holds the owner lock; never bump the user's global version."""
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.family_id == family_id,
                RefreshToken.user_id.in_(select(User.id)),
            )
            .values(revoked=True)
        )

    async def revoke_session(
        self, *, access_token: str | None = None, refresh_token: str | None = None
    ) -> None:
        """Revoke one refresh family by possession; access JWTs retain their TTL.

        Valid signed access JWTs may end only their own family. Legacy JWTs
        without sid require a refresh credential. No credential grants broader
        authority here, and tenant-scoped user visibility is still required.
        """
        if access_token is not None:
            try:
                payload = jwt.decode(
                    access_token,
                    settings.jwt_secret_key.get_secret_value(),
                    algorithms=[settings.jwt_algorithm],
                    options={"require": ["sub", "sid", "exp"]},
                )
                user_id = uuid.UUID(payload["sub"])
                family_id = uuid.UUID(payload["sid"])
            except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError("Invalid session credential") from exc
            predicate = (
                RefreshToken.user_id == user_id,
                RefreshToken.family_id == family_id,
            )
        elif refresh_token:
            predicate = (
                RefreshToken.token_hash
                == hashlib.sha256(refresh_token.encode()).hexdigest(),
            )
        else:
            raise ValueError("Invalid session credential")
        row = (
            await self.db.execute(
                select(RefreshToken.user_id, RefreshToken.family_id)
                .join(User, RefreshToken.user_id == User.id)
                .where(*predicate)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Invalid session credential")
        await self.db.execute(
            select(User.id).where(User.id == row.user_id).with_for_update()
        )
        await self._revoke_family(row.user_id, row.family_id)
        await self.db.commit()

    async def revoke_all_tokens(
        self, user_id: uuid.UUID, *, commit: bool = True, bump_key_epoch: bool = False
    ) -> int:
        """Revoke all active refresh tokens AND bump User.token_version (logout).

        SEC-S15 (Phase 1062-01): incrementing token_version invalidates every
        access JWT issued before the bump on the next authenticated request,
        closing the "logout doesn't invalidate access JWT" gap.

        commit=False lets the caller fold revocation into a larger
        transaction (e.g. change_password, where the password hash and audit
        row must land in the same commit).

        bump_key_epoch (fix(#821)) also bumps User.key_epoch, invalidating
        every API key minted before the bump. Default False so plain logout
        never kills long-lived API keys; pass True only from security-event
        callers.

        Returns the new token_version value.
        """
        # fix(#1446): take the owner-row lock BEFORE revoking, matching
        # rotate_refresh_token — a concurrent rotation must either finish
        # before this UPDATE's snapshot (so its replacement is caught) or
        # block here and find its own row already revoked.
        await self.db.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

        # 1. Revoke all active refresh tokens for the user.
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id.in_(select(User.id).where(User.id == user_id)),
                RefreshToken.revoked == False,  # noqa: E712
            )
            .values(revoked=True)
        )

        # 2. Atomically increment token_version (and key_epoch, if requested,
        #    in the same UPDATE) so prior access JWTs/API keys are rejected.
        #
        #    fix(#1455): stamp the revocation horizon in the same UPDATE.
        #    Step 1 only revokes what its own snapshot sees, so a rotation
        #    committing its replacement just after that snapshot survives —
        #    the horizon is a predicate evaluated at USE time, the only shape
        #    that covers a row this transaction can't see yet. func.now() is
        #    the transaction timestamp, matching RefreshToken.created_at
        #    (skew-free). GREATEST keeps the horizon monotonic if the clock
        #    steps backward; COALESCE is needed because SQL GREATEST is not
        #    guaranteed to ignore NULLs (Postgres does, the standard doesn't).
        #
        #    token_version is retained, not replaced: iat is API-clock and
        #    the horizon is DB-clock, so a fast API clock could mint a
        #    pre-logout token whose iat clears the horizon — the bump still
        #    kills it. And since iat is whole seconds, the same-second region
        #    is covered by the bump ALONE (see _predates_revocation_horizon
        #    in dependencies.py). Weakening this bump requires tightening
        #    that rounding in the same change; this stays purely additive.
        values: dict = {
            "token_version": User.token_version + 1,
            "sessions_revoked_at": func.greatest(
                func.coalesce(
                    User.sessions_revoked_at,
                    literal_column("'-infinity'::timestamptz"),
                ),
                func.now(),
            ),
        }
        if bump_key_epoch:
            values["key_epoch"] = User.key_epoch + 1
        version_result = await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(**values)
            .returning(User.token_version)
        )
        new_version = version_result.scalar_one_or_none()
        if new_version is None:
            raise ValueError("User not found")

        if commit:
            await self.db.commit()
        return new_version

    async def revoke_all_refresh_tokens(self, user_id: uuid.UUID) -> int:
        """Backward-compatible alias for revoke_all_tokens.

        Delegates to revoke_all_tokens (which also bumps token_version), so
        direct callers outside the auth router get the same semantics.
        Returns the new token_version value (previously returned rowcount —
        callers depending on the exact value should switch to
        revoke_all_tokens directly).
        """
        return await self.revoke_all_tokens(user_id)

    async def register_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
    ) -> uuid.UUID:
        """Create a new pending user (no role assigned). Returns the new user id.

        Raises ValueError if the username or email already exists.

        ADMIN-05 (L-02): FLUSHES but does NOT commit — the caller controls
        the transaction so a follow-up audit_emit lands in the same one.
        """
        existing = await self.db.execute(
            select(User).where(func.lower(User.username) == func.lower(username))
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("Username or email already taken")

        if email is not None:
            existing_email = await self.db.execute(
                select(User).where(func.lower(User.email) == func.lower(email))
            )
            if existing_email.scalar_one_or_none() is not None:
                raise ValueError("Username or email already taken")

        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email,
            status="pending",
            is_active=False,
        )
        self.db.add(user)
        # Flush so user.id is populated (server_default UUID); caller commits.
        await self.db.flush()
        return user.id

    # Note: duplicates visibility.get_user_roles — consider delegating
    async def get_user_roles(self, user_id: uuid.UUID) -> set[str]:
        result = await self.db.execute(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        return {row[0] for row in result.all()}


# Shared API key helper (used by admin and self-service routers).
class ApiKeyTargetUserNotFoundError(LookupError):
    """The target user is absent from the caller's RLS-visible scope."""


class ApiKeyTargetUserInactiveError(ValueError):
    """The target user is not active, so an API key must not be minted.

    fix(#821): a key minted for a pending account would be blocked by the
    resolution-time status check while pending, then gain the approved
    role's privileges at approval. Refusing the mint closes that door early
    (approve_user's key_epoch bump is belt-and-suspenders for keys that
    predate this guard).
    """


async def create_api_key_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    expires_at: datetime | None = None,
    scope: str = "full",
) -> tuple[ApiKey, str]:
    """Create an API key for a user. Returns (api_key, raw_key).

    The raw key is only available at creation time. Flushes but does
    NOT commit — caller controls the transaction.

    fix(#821): ``expires_at=None`` mints a non-expiring key (legacy
    behavior); the key snapshots the owner's key_epoch so a later security
    event (password/role change, SAML-to-local conversion — NOT logout)
    invalidates it. Minting requires an active owner.

    fix(#875): ``scope="read_only"`` mints a key that authenticates only
    GET/HEAD/OPTIONS. Default matches the column default.
    """
    owner = (
        await db.execute(
            select(User.id, User.key_epoch, User.status).where(User.id == user_id)
        )
    ).one_or_none()
    if owner is None:
        raise ApiKeyTargetUserNotFoundError("User not found")
    if owner.status != "active":
        raise ApiKeyTargetUserInactiveError(
            "API keys can only be created for active users"
        )

    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    fingerprint = f"{raw_key[:8]}…{raw_key[-4:]}"
    api_key = ApiKey(
        user_id=owner.id,
        key_hash=key_hash,
        fingerprint=fingerprint,
        name=name,
        expires_at=expires_at,
        key_epoch=owner.key_epoch,
        scope=scope,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    return api_key, raw_key
