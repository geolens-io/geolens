"""Email-verification token service (SIGNUP-03/05).

Opaque single-use tokens, mirroring the ``RefreshToken`` pattern: the raw
token goes to the caller and only its sha256 hash is persisted. Redemption
returns ``None`` uniformly for expired, unknown, and already-consumed tokens
(enumeration-safe, SIGNUP-05). Callers own the transaction (flush, not
commit).
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

    Returns the raw token; only its sha256 hash is persisted. Flush-not-commit
    — caller owns the transaction.
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

    Returns the user's UUID on success, else ``None`` — expired, unknown, and
    already-consumed tokens all return ``None`` identically (enumeration-safe,
    SIGNUP-05: no timing or response difference leaks whether the email
    exists).
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)

    # Atomic claim: the predicate is evaluated under the row lock this UPDATE
    # takes, so two concurrent redemptions can't both pass consumed_at IS NULL
    # — the loser matches 0 rows and gets None.
    result = await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.expires_at > now,
            EmailVerificationToken.user_id.in_(select(User.id)),
        )
        .values(consumed_at=now)
        .returning(EmailVerificationToken.user_id)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        # Covers: expired, unknown, already-consumed, or lost the race.
        return None

    # Flip email_verified on the user via a targeted UPDATE.
    await db.execute(update(User).where(User.id == user_id).values(email_verified=True))

    # Flush-not-commit: caller owns the transaction.
    await db.flush()
    return user_id
