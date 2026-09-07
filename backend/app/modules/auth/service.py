"""Auth service: JWT token creation, refresh tokens, and user registration."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import func, literal_column, or_, select, update
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
        self, user_id: uuid.UUID, expire_days: int | None = None
    ) -> str:
        """expire_days falls back to settings.refresh_token_expire_days if None."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        days = expire_days or settings.refresh_token_expire_days
        expires_at = datetime.now(UTC) + timedelta(days=days)
        refresh = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
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

        fix(#621): "retire" rather than "revoke" — the used token keeps a
        short grace window (refresh_rotation_grace_seconds) during which a
        concurrent caller can still rotate it and mint its own valid pair.

        Returns (new_access_token, new_refresh_token).
        Raises ValueError on invalid/expired/revoked token or inactive user.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken)
            .join(User, RefreshToken.user_id == User.id)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
                RefreshToken.expires_at > datetime.now(UTC),
                # fix(#1455): revocation horizon, checked at use time — covers
                # a replacement row committed just after revoke_all_tokens'
                # snapshot, which would otherwise rotate into a session that
                # outlives its own logout.
                or_(
                    User.sessions_revoked_at.is_(None),
                    RefreshToken.created_at > User.sessions_revoked_at,
                ),
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            raise ValueError("Invalid or expired refresh token")

        # fix(#1446): serialize against revoke_all_tokens on the OWNER row —
        # both paths take this lock first, which makes both interleavings
        # safe: if rotate wins, it commits its replacement before revoke's
        # UPDATE takes its snapshot, so revoke still catches the new row; if
        # revoke wins, rotate's re-check below sees revoked=True and raises
        # instead of minting a successor. Without it, a rotation could commit
        # a still-active replacement after a concurrent logout — reviving a
        # session the user ended (compounded by fix(#1302) reinstalling the
        # cookies logout just deleted).
        user_result = await self.db.execute(
            select(User).where(User.id == stored.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active or user.status != "active":
            raise ValueError("User account is not active")

        # Re-read the presented row now that the lock is held — a new
        # statement takes a new snapshot, so anything committed while we
        # waited is visible. Must run BEFORE the retire/revoke write below,
        # since that write autoflushes and would make this re-check see our
        # own pending mutation instead.
        #
        # fix(#1446): re-check liveness, not just revoked — the wait is
        # unbounded, so the token can lapse (its own expiry, or a queued
        # rotation shortening it to the grace cutoff) while we wait. A token
        # still inside the grace window has a future expires_at and stays
        # accepted (fix(#621)).
        recheck = await self.db.execute(
            select(RefreshToken.revoked, RefreshToken.expires_at).where(
                RefreshToken.id == stored.id
            )
        )
        current = recheck.one_or_none()
        if (
            current is None
            or current.revoked
            or current.expires_at <= datetime.now(UTC)
        ):
            raise ValueError("Invalid or expired refresh token")

        # fix(#621): rotation grace window. Instant revocation stranded the
        # losers of a multi-tab refresh race — one tab wins, the rest got a
        # dead credential (observed as a recurring 200+401+401 pattern, once
        # a 7-hour silent tile-403 spiral). Instead of revoking, shorten the
        # used token's remaining lifetime to a small grace window: a
        # concurrent caller inside it still mints its own pair, then the
        # token expires naturally. Never EXTEND a token already closer to
        # expiry. Explicit revocation (logout / revoke_all_tokens) still sets
        # revoked=True on in-grace rows, so a hard logout stays instant.
        # grace=0 restores single-use revocation.
        #
        # fix(#1446): compares against the POST-LOCK expiry (`current`), not
        # the pre-lock `stored` object — queued refreshes reading the same
        # token would otherwise each see the original expiry and push
        # retirement further out, the opposite of "never EXTEND".
        grace = settings.refresh_rotation_grace_seconds
        if grace > 0:
            grace_cutoff = datetime.now(UTC) + timedelta(seconds=grace)
            if current.expires_at > grace_cutoff:
                stored.expires_at = grace_cutoff
        else:
            stored.revoked = True

        identity = AuthenticatedIdentity(user_id=user.id, username=user.username)
        new_access = await self.create_access_token(
            identity, expire_minutes=expire_minutes
        )
        new_refresh = self.create_refresh_token(user.id, expire_days=expire_days)

        # Opportunistic cleanup: delete expired tokens older than 1 day
        from sqlalchemy import delete

        await self.db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < datetime.now(UTC) - timedelta(days=1),
                RefreshToken.user_id.in_(select(User.id)),
            )
        )

        await self.db.commit()
        return new_access, new_refresh

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
