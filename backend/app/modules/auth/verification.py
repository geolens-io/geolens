"""Email-verification token service (Phase 1231 / SIGNUP-03/05).

Provides two async functions that mirror the ``RefreshToken`` opaque-token
pattern from ``app.modules.auth.service``:

- ``issue_verification_token(db, user_id, expire_hours=24) -> str``
  Issues a single-use expiring verification token.  The raw token is returned
  to the caller (to embed in the verification link email); only its sha256 hex
  digest is persisted.  Flush-not-commit: the caller owns the transaction.

- ``redeem_verification_token(db, raw_token) -> uuid.UUID | None``
  Validates the raw token (hash lookup, expiry check, consumed_at check) and,
  on success, sets ``User.email_verified = True`` and marks the token consumed.
  Returns the user's UUID on success or ``None`` on any failure — expired,
  unknown, and already-consumed tokens all return the same ``None`` sentinel
  (enumeration-safe, SIGNUP-05).  Flush-not-commit.

Security: T-1231-01..03.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import EmailVerificationToken, User


async def issue_verification_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    expire_hours: int = 24,
) -> str:
    """Issue a single-use expiring verification token for *user_id*.

    The raw urlsafe token is returned to the caller (embed in the email link).
    Only the sha256 hex digest is stored — the plaintext is never persisted
    (mirrors RefreshToken: ``secrets.token_urlsafe(32)`` + ``hashlib.sha256``).

    Args:
        db: Async SQLAlchemy session (caller owns the transaction).
        user_id: The user to issue the token for.
        expire_hours: Token lifetime in hours (default 24).

    Returns:
        The raw opaque verification token (URL-safe base64, 32 bytes entropy).
    """
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=expire_hours)

    token = EmailVerificationToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(token)
    # Flush-not-commit: caller owns the transaction (mirrors create_refresh_token).
    await db.flush()
    return raw


async def redeem_verification_token(
    db: AsyncSession,
    raw_token: str,
) -> uuid.UUID | None:
    """Redeem a raw verification token, activating the user's email.

    Validates the token (hash lookup, expiry, consumed_at) and, on success:
    - sets ``consumed_at`` on the token row (single-use gate), and
    - sets ``User.email_verified = True`` via a targeted UPDATE.

    Returns the user's UUID on success, or ``None`` on any failure.
    Expired, unknown, and already-consumed tokens all return ``None``
    identically (enumeration-safe, SIGNUP-05: no timing or response
    difference leaks whether the email address exists).

    Args:
        db: Async SQLAlchemy session (caller owns the transaction).
        raw_token: The raw opaque token from the verification URL.

    Returns:
        The user's UUID if the token was valid and just consumed, else None.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.expires_at > datetime.now(UTC),
        )
    )
    token_row = result.scalar_one_or_none()
    if token_row is None:
        # Covers: expired, unknown, already-consumed — same None sentinel.
        return None

    # Mark consumed (single-use gate).
    token_row.consumed_at = datetime.now(UTC)

    # Flip email_verified on the user via a targeted UPDATE.
    await db.execute(
        update(User).where(User.id == token_row.user_id).values(email_verified=True)
    )

    # Flush-not-commit: caller owns the transaction.
    await db.flush()
    return token_row.user_id
