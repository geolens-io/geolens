"""Unit tests for the email-verification token service (Phase 1231 / SIGNUP-03/05).

Covers:
- issue_verification_token stores only the sha256 hash (plaintext never at rest)
- Returned token is a raw urlsafe string (not the hash)
- Valid unexpired unconsumed token → redeem flips email_verified=True + consumes token
- Double-redeem of the same token → returns None (single-use gate)
- Expired token → returns None + does NOT flip email_verified
- Unknown/garbage token → returns None (enumeration-safe: same sentinel as expired)
- EMAIL_VERIFICATION_REQUIRED defaults to True with no DB override

Run with:
    cd backend && set -a && source ../.env.test && set +a &&
    uv run pytest tests/test_email_verification_token.py -x -q
"""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.auth.models import EmailVerificationToken, User
from app.modules.auth.verification import (
    issue_verification_token,
    redeem_verification_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_user(session, username_suffix: str | None = None) -> User:
    """Insert a minimal User row and return it."""
    suffix = username_suffix or uuid.uuid4().hex[:8]
    user = User(
        username=f"verify_test_{suffix}",
        email=f"verify_{suffix}@example.com",
        is_active=True,
        status="active",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Tests: issue_verification_token
# ---------------------------------------------------------------------------


class TestIssueVerificationToken:
    async def test_returns_raw_token_not_hash(self, test_db_session):
        """issue_verification_token returns a raw urlsafe string."""
        user = await _create_test_user(test_db_session)
        raw = await issue_verification_token(test_db_session, user.id)

        assert isinstance(raw, str)
        assert len(raw) >= 32, "raw token should be at least 32 characters"

    async def test_stores_only_hash_not_plaintext(self, test_db_session):
        """The raw token is never persisted — only its sha256 hex digest is stored."""
        user = await _create_test_user(test_db_session)
        raw = await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        expected_hash = hashlib.sha256(raw.encode()).hexdigest()

        result = await test_db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        token_row = result.scalar_one()

        # The stored hash must equal the sha256 digest of the raw token.
        assert token_row.token_hash == expected_hash, (
            "stored token_hash is not the sha256 of the raw token"
        )
        # The raw token must NOT equal the stored hash (no plaintext at rest).
        assert raw != token_row.token_hash, "raw token must not be stored in plaintext"

    async def test_expires_at_in_the_future(self, test_db_session):
        """Issued token has an expiry in the future."""
        user = await _create_test_user(test_db_session)
        await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        token_row = result.scalar_one()
        assert token_row.expires_at > datetime.now(UTC), (
            "token expires_at must be in the future"
        )

    async def test_consumed_at_is_null_on_issue(self, test_db_session):
        """A freshly issued token is not yet consumed."""
        user = await _create_test_user(test_db_session)
        await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        token_row = result.scalar_one()
        assert token_row.consumed_at is None, (
            "a freshly issued token must have consumed_at=None"
        )


# ---------------------------------------------------------------------------
# Tests: redeem_verification_token — happy path
# ---------------------------------------------------------------------------


class TestRedeemVerificationTokenHappyPath:
    async def test_valid_token_returns_user_id(self, test_db_session):
        """Redeeming a valid unexpired unconsumed token returns the user's UUID."""
        user = await _create_test_user(test_db_session)
        raw = await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        result_user_id = await redeem_verification_token(test_db_session, raw)

        assert result_user_id == user.id, (
            f"expected user_id={user.id!r}, got {result_user_id!r}"
        )

    async def test_valid_token_flips_email_verified(self, test_db_session):
        """Redeeming a valid token sets User.email_verified=True."""
        user = await _create_test_user(test_db_session)
        # Verify starts as False.
        assert user.email_verified is False

        raw = await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        await redeem_verification_token(test_db_session, raw)
        await test_db_session.flush()

        # Re-read user from DB.
        await test_db_session.refresh(user)
        assert user.email_verified is True, (
            "email_verified must be True after redemption"
        )

    async def test_valid_token_sets_consumed_at(self, test_db_session):
        """Redeeming a valid token marks the token as consumed."""
        user = await _create_test_user(test_db_session)
        raw = await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        await redeem_verification_token(test_db_session, raw)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        token_row = result.scalar_one()
        assert token_row.consumed_at is not None, (
            "consumed_at must be set after redemption"
        )


# ---------------------------------------------------------------------------
# Tests: redeem_verification_token — error cases (all return None)
# ---------------------------------------------------------------------------


class TestRedeemVerificationTokenErrorCases:
    async def test_double_redeem_returns_none(self, test_db_session):
        """Redeeming the same token twice returns None (single-use gate)."""
        user = await _create_test_user(test_db_session)
        raw = await issue_verification_token(test_db_session, user.id)
        await test_db_session.flush()

        # First redemption must succeed.
        first_result = await redeem_verification_token(test_db_session, raw)
        await test_db_session.flush()
        assert first_result == user.id

        # Second redemption must return None.
        second_result = await redeem_verification_token(test_db_session, raw)
        assert second_result is None, (
            "second redemption of the same token must return None (single-use)"
        )

    async def test_expired_token_returns_none(self, test_db_session):
        """An expired token returns None and does NOT flip email_verified."""
        user = await _create_test_user(test_db_session)

        # Issue a token that expires immediately (in the past).
        raw = await issue_verification_token(test_db_session, user.id, expire_hours=-1)
        await test_db_session.flush()

        result = await redeem_verification_token(test_db_session, raw)

        assert result is None, (
            "expired token must return None (enumeration-safe: same as unknown)"
        )
        # email_verified must NOT have been flipped.
        await test_db_session.refresh(user)
        assert user.email_verified is False, (
            "email_verified must remain False after expired-token redemption attempt"
        )

    async def test_unknown_garbage_token_returns_none(self, test_db_session):
        """Redeeming a garbage/unknown token returns None (enumeration-safe)."""
        garbage = "thisisnotavalidtokenstringXYZ9999"
        result = await redeem_verification_token(test_db_session, garbage)
        assert result is None, (
            "unknown token must return None (same sentinel as expired)"
        )


# ---------------------------------------------------------------------------
# Tests: EMAIL_VERIFICATION_REQUIRED config default
# ---------------------------------------------------------------------------


class TestEmailVerificationRequiredConfig:
    async def test_defaults_to_true(self, test_db_session):
        """EMAIL_VERIFICATION_REQUIRED.get(db) defaults to True with no DB override."""
        from app.core.persistent_config import EMAIL_VERIFICATION_REQUIRED

        value = await EMAIL_VERIFICATION_REQUIRED.get(test_db_session)
        assert value is True, (
            f"EMAIL_VERIFICATION_REQUIRED must default to True, got {value!r}"
        )
