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

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------

    async def create_access_token(
        self,
        identity: AuthenticatedIdentity,
        expire_minutes: int | None = None,
    ) -> str:
        """Create a signed JWT for the given identity.

        SEC-S15 (Phase 1062-01): the payload now includes:
          - ``jti``: uuid4 hex — a unique token identifier (128 random bits).
          - ``token_version``: current User.token_version value. Any JWT whose
            token_version is less than the user's current column value is
            rejected by get_current_user / get_optional_user, making logout
            and password-change revocations take effect on the next request.

        Args:
            identity: The authenticated user identity.
            expire_minutes: Override token lifetime (minutes). Falls back to
                settings.access_token_expire_minutes if None.
        """
        minutes = expire_minutes or settings.access_token_expire_minutes
        now = datetime.now(UTC)
        multi_tenant = is_multi_tenant()

        # Load token_version for this user so we can embed it in the JWT.
        # Using a column-only select avoids a redundant full-row read when the
        # User row was already loaded by the caller (e.g. the login handler),
        # but it is a safe extra query — correctness over micro-optimisation.
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
        # WR-04: use an explicit None check rather than `or 1` so a DB row with
        # token_version=0 is not silently coerced to 1. In normal operation
        # token_version starts at 1 (migration server_default="1"), so 0 is
        # unreachable — but explicit intent is clearer than relying on falsiness.
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

        SEC-04 / M-66: a JWT in a URL query parameter is far more leak-prone
        than a Bearer header (browser history, server logs, accidental copy).
        Issuing a separate token with ``typ='download'``, an explicit ``scope``
        binding the token to one dataset, and a ≤2-minute TTL bounds the
        damage if the URL is exposed. The session JWT continues to work via
        the Authorization header — only the ?token= lane is restricted.

        ``expire_seconds`` is capped at 120 by validation; callers passing a
        larger value get the cap applied silently. Capped form, never raised.
        """
        # Cap TTL to 120s — defense against caller mis-configuration.
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

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    def create_refresh_token(
        self, user_id: uuid.UUID, expire_days: int | None = None
    ) -> str:
        """Create an opaque refresh token, store hash in DB, return raw token.

        Args:
            user_id: The user to issue the token for.
            expire_days: Override token lifetime (days). Falls back to
                settings.refresh_token_expire_days if None.
        """
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

        CR-01 (Phase 1236 Plan 03): used by the refresh handler to load the
        user so an allowlist domain-check can be applied BEFORE the old token
        is revoked. The caller is responsible for calling rotate_refresh_token
        only after the check passes — keeping the token intact on rejection so
        the user still has a usable token (no silent revocation on block).

        Returns None when the token is missing, expired, or already revoked.
        Returns None when the linked user does not exist.
        Returns None when the row predates the owner's revocation horizon.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken)
            .join(User, RefreshToken.user_id == User.id)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
                RefreshToken.expires_at > datetime.now(UTC),
                # fix(#1455): the revocation horizon, checked at use time so it
                # covers rows revoke_all_tokens could not see when it ran.
                # Both timestamps come from the DB clock, so the comparison is
                # skew-free. A successor login's row is stamped after the
                # horizon and passes without any client choreography.
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

        Args:
            raw_token: The raw refresh token to validate.
            expire_minutes: Override access token lifetime (minutes).
            expire_days: Override refresh token lifetime (days).

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
                # fix(#1455): the revocation horizon, checked at use time so it
                # covers rows revoke_all_tokens could not see when it ran — the
                # replacement a rotation commits just after the revoking
                # statement took its snapshot is unrevoked and, without this,
                # rotates into a fresh session that outlives its own logout.
                or_(
                    User.sessions_revoked_at.is_(None),
                    RefreshToken.created_at > User.sessions_revoked_at,
                ),
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            raise ValueError("Invalid or expired refresh token")

        # fix(#1446): serialize against revoke_all_tokens on the OWNER row.
        # Both paths now take this lock first, which is what makes the two
        # interleavings safe:
        #   - rotate wins the lock: it inserts its replacement and commits;
        #     revoke then runs its UPDATE afterwards, and because that
        #     statement takes a fresh snapshot it sees and revokes the new row.
        #   - revoke wins: it revokes and commits; rotate acquires the lock and
        #     the re-check below sees revoked=True, so it raises instead of
        #     minting a successor.
        # Without it, a rotation that read its row before a concurrent logout
        # could commit a still-active replacement afterwards — and since
        # fix(#1302) that also reinstalls the cookies the logout just deleted,
        # reviving a session the user ended.
        user_result = await self.db.execute(
            select(User).where(User.id == stored.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active or user.status != "active":
            raise ValueError("User account is not active")

        # Re-read the presented row now that the lock is held. A new statement
        # takes a new snapshot, so anything that committed while we waited is
        # visible here and cannot be rotated past. This must run BEFORE the
        # retire/revoke below: that write autoflushes, and the re-check would
        # then read back our own pending mutation and reject a valid token.
        #
        # fix(#1446): re-check liveness, not just revocation. Waiting on the
        # lock is unbounded, so the token can lapse in the meantime — either by
        # simply reaching its own expiry, or because the rotation we were
        # queued behind shortened it to the grace cutoff. Checking `revoked`
        # alone would happily rotate an expired token into a fresh session.
        # A token still inside the grace window has a future expires_at and is
        # deliberately still accepted (fix(#621)).
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
        # losers of a multi-tab refresh race: every tab presents the same
        # rotating token, one caller wins, and the rest were left holding a
        # dead credential (observed live as recurring `200+401+401` triplets,
        # ending in a 7-hour silent tile-403 spiral). Instead of revoking,
        # shorten the used token's remaining lifetime to a small grace window:
        # a concurrent caller presenting it inside the window mints its own
        # valid pair (a short-lived family branch), then the token expires
        # naturally. Never EXTEND a token that is already closer to expiry.
        # Explicit revocation (logout / revoke_all_tokens) still sets
        # revoked=True on every active row — in-grace ones included — so a
        # hard logout remains instant. grace=0 restores single-use revocation.
        #
        # fix(#1446): compare against the POST-LOCK expiry (`current`), not the
        # `stored` ORM object read before the lock. When several refreshes read
        # the same long-lived token and then queue here, every queued caller
        # still holds the original multi-day expiry on `stored`, so each would
        # find it later than its own cutoff and push the retirement further
        # out — ratcheting the window open instead of closing it, which is the
        # opposite of "never EXTEND".
        grace = settings.refresh_rotation_grace_seconds
        if grace > 0:
            grace_cutoff = datetime.now(UTC) + timedelta(seconds=grace)
            if current.expires_at > grace_cutoff:
                stored.expires_at = grace_cutoff
        else:
            stored.revoked = True

        # Issue new pair
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
        access JWT issued before the bump on the next authenticated request.
        Combined with refresh-token revocation this closes the
        "logout doesn't invalidate access JWT" gap.

        Args:
            user_id: The user whose tokens should be revoked.
            commit: If True (default), commit the transaction immediately so the
                revocation is durable. Pass commit=False when the caller wants to
                fold revocation into a larger transaction (e.g. change_password,
                where the password hash and audit row must land in the same commit).
            bump_key_epoch: fix(#821) — also bump User.key_epoch, invalidating
                every API key minted before the bump. Default False so plain
                logout (session hygiene) never kills long-lived API keys; pass
                True only from security-event callers (password change).

        Returns the new token_version value.
        """
        # fix(#1446): take the owner-row lock BEFORE revoking, matching
        # rotate_refresh_token. Ordering is the whole point — a concurrent
        # rotation must either finish before this revocation's UPDATE takes its
        # snapshot (so its replacement row is seen and revoked) or block here
        # and find its own row already revoked.
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

        # 2. Atomically increment token_version so prior access JWTs are
        #    rejected (and key_epoch in the same UPDATE when requested, so a
        #    security event revokes JWTs and API keys atomically).
        #
        #    fix(#1455): stamp the revocation horizon in the same UPDATE. Step 1
        #    can only revoke what its own snapshot sees, so a rotation that
        #    commits its replacement row just after that snapshot survives this
        #    revocation; the horizon is a predicate evaluated at USE time, which
        #    is the only shape that covers a row this transaction cannot see
        #    yet. func.now() is the transaction timestamp — the same clock that
        #    stamps RefreshToken.created_at, so the refresh comparison has no
        #    skew axis. GREATEST keeps the horizon monotonic if the DB clock
        #    ever steps backwards. COALESCE is not redundant: Postgres GREATEST
        #    happens to ignore NULLs, but the SQL standard propagates them, and
        #    this must not depend on which behavior we get.
        #
        #    The token_version bump below is retained, not replaced, and the
        #    access-JWT half of #1455 DEPENDS on it in two ways. iat comes from
        #    the API process clock and the horizon from the DB clock, so an API
        #    clock running ahead could mint a pre-logout token whose iat clears
        #    the horizon — the bump is what still kills it. And because iat is
        #    whole seconds, the same-second region is covered by the bump
        #    ALONE: _predates_revocation_horizon in auth/dependencies.py rounds
        #    toward accepting on exactly that basis. Removing or weakening this
        #    bump requires tightening that rounding in the same change.
        #    Together they are what makes this purely additive: no credential
        #    rejected today becomes acceptable.
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

        Delegates to revoke_all_tokens (which also bumps token_version) so
        any direct callers outside the auth router get the same revocation
        semantics without a breaking API change.

        Returns the new token_version value (previously returned rowcount —
        callers that depended on the exact return value should switch to
        revoke_all_tokens directly).
        """
        return await self.revoke_all_tokens(user_id)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
    ) -> uuid.UUID:
        """Create a new pending user (no role assigned). Returns the new user id.

        Raises ValueError if the username or email already exists.

        Phase 279 ADMIN-05 (L-02): contract change — this method now FLUSHES but
        does NOT commit. The caller controls the transaction so a follow-up
        audit_emit can land in the same transaction as the user insert. The
        returned UUID is the new user's id (populated by ``flush()``).
        """
        # Check username uniqueness (case-insensitive)
        existing = await self.db.execute(
            select(User).where(func.lower(User.username) == func.lower(username))
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("Username or email already taken")

        # Check email uniqueness (if provided)
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

    # ------------------------------------------------------------------
    # Role queries
    # ------------------------------------------------------------------

    # Note: duplicates visibility.get_user_roles — consider delegating
    async def get_user_roles(self, user_id: uuid.UUID) -> set[str]:
        """Return the set of role names for a given user."""
        result = await self.db.execute(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        return {row[0] for row in result.all()}


# ------------------------------------------------------------------
# Shared API key helper (used by admin and self-service routers)
# ------------------------------------------------------------------


class ApiKeyTargetUserNotFoundError(LookupError):
    """The target user is absent from the caller's RLS-visible scope."""


class ApiKeyTargetUserInactiveError(ValueError):
    """The target user is not active, so an API key must not be minted.

    fix(#821 codex review): a key minted for a pending account would be
    blocked by the resolution-time status check while pending, then wake up
    with the approved role's privileges at approval. Refusing the mint closes
    that door at the earliest point (approve_user's key_epoch bump is the
    belt-and-suspenders for keys that predate this guard).
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

    fix(#821): ``expires_at=None`` mints a non-expiring key (legacy behavior);
    the key also snapshots the owner's current key_epoch so a later security
    event (password change, role change, SAML-to-local conversion — NOT
    logout) invalidates it. Minting requires an active owner.

    fix(#875): ``scope="read_only"`` mints a key that authenticates only
    GET/HEAD/OPTIONS. The default matches the column default, so a caller that
    does not care keeps the pre-existing behavior. Values are constrained by
    the request schemas above this and by ``chk_api_keys_scope`` below it.
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
