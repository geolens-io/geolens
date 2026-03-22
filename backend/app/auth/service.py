"""Auth service: JWT token creation, refresh tokens, and user registration."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken, Role, User, UserRole
from app.auth.providers import AuthenticatedIdentity
from app.auth.providers.local import hash_password
from app.config import settings


class AuthService:
    """Handles JWT creation, user registration, and role queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------

    def create_access_token(
        self,
        identity: AuthenticatedIdentity,
        expire_minutes: int | None = None,
    ) -> str:
        """Create a signed JWT for the given identity.

        Args:
            identity: The authenticated user identity.
            expire_minutes: Override token lifetime (minutes). Falls back to
                settings.access_token_expire_minutes if None.
        """
        minutes = expire_minutes or settings.access_token_expire_minutes
        now = datetime.now(UTC)
        payload = {
            "sub": str(identity.user_id),
            "username": identity.username,
            "exp": now + timedelta(minutes=minutes),
            "iat": now,
        }
        return jwt.encode(
            payload,
            settings.jwt_secret_key,
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

    async def rotate_refresh_token(
        self,
        raw_token: str,
        expire_minutes: int | None = None,
        expire_days: int | None = None,
    ) -> tuple[str, str]:
        """Validate refresh token, revoke it, issue new access + refresh pair.

        Args:
            raw_token: The raw refresh token to validate.
            expire_minutes: Override access token lifetime (minutes).
            expire_days: Override refresh token lifetime (days).

        Returns (new_access_token, new_refresh_token).
        Raises ValueError on invalid/expired/revoked token or inactive user.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
                RefreshToken.expires_at > datetime.now(UTC),
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            raise ValueError("Invalid or expired refresh token")

        # Revoke used token (rotation)
        stored.revoked = True

        # Load user and verify active status
        user_result = await self.db.execute(
            select(User).where(User.id == stored.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active or user.status != "active":
            raise ValueError("User account is not active")

        # Issue new pair
        identity = AuthenticatedIdentity(user_id=user.id, username=user.username)
        new_access = self.create_access_token(identity, expire_minutes=expire_minutes)
        new_refresh = self.create_refresh_token(user.id, expire_days=expire_days)

        # Opportunistic cleanup: delete expired tokens older than 1 day
        from sqlalchemy import delete

        await self.db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < datetime.now(UTC) - timedelta(days=1)
            )
        )

        await self.db.commit()
        return new_access, new_refresh

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
    ) -> User:
        """Create a new pending user (no role assigned).

        Raises ValueError if the username or email already exists.
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
        await self.db.commit()
        return user

    # ------------------------------------------------------------------
    # Role queries
    # ------------------------------------------------------------------

    async def get_user_roles(self, user_id: uuid.UUID) -> set[str]:
        """Return the set of role names for a given user."""
        result = await self.db.execute(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        return {row[0] for row in result.all()}
