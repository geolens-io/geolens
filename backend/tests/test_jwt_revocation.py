"""Tests for JWT revocation via User.token_version (SEC-S15, Phase 1062-01).

Covers:
  - JWT payload carries jti (32-char hex) and token_version claims.
  - Bumping token_version invalidates prior JWTs on next request.
  - Not bumping token_version keeps the JWT valid.
  - Legacy JWTs without a token_version claim are rejected (treated as version 0).
  - POST /auth/logout/ bumps token_version so prior access JWT returns 401.
  - POST /auth/change-password/ bumps token_version so prior access JWT returns 401.
"""

import uuid
from unittest.mock import AsyncMock

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.providers.local import hash_password
from app.modules.auth.router import REGISTRATION_ENABLED
from app.modules.auth.service import AuthService

pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

# A password that satisfies the new policy (12 chars, 3+ classes).
STRONG_PASSWORD = "TestPass1234!"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """Log in and return the full token response JSON."""
    resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()


async def _create_local_user(
    client: AsyncClient,
    admin_headers: dict,
    username: str,
    password: str = STRONG_PASSWORD,
) -> str:
    """Create a user through the admin endpoint and return the user_id."""
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": "viewer"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Create user failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# JWT payload tests (no HTTP, pure service-level)
# ---------------------------------------------------------------------------


class TestJwtPayloadClaims:
    """Verify that create_access_token embeds jti and token_version."""

    async def test_jwt_carries_jti_and_token_version(self, client: AsyncClient):
        """Issued access JWT must have a 32-char hex jti and an integer token_version."""
        tokens = await _login(client, ADMIN_USER, ADMIN_PASS)
        raw = tokens["access_token"]

        # Decode without verification to inspect the payload claims directly.
        payload = jwt.decode(
            raw,
            options={"verify_signature": False},
            algorithms=[settings.jwt_algorithm],
        )

        assert "jti" in payload, "JWT must include a jti claim"
        assert isinstance(payload["jti"], str)
        assert len(payload["jti"]) == 32, "jti must be a 32-char uuid4 hex string"
        # Confirm it is valid hex.
        assert all(c in "0123456789abcdef" for c in payload["jti"])

        assert "token_version" in payload, "JWT must include a token_version claim"
        assert isinstance(payload["token_version"], int)
        assert payload["token_version"] >= 1, "token_version must be >= 1"


# ---------------------------------------------------------------------------
# Token-version revocation tests (via DB mutation + GET /auth/me/)
# ---------------------------------------------------------------------------


class TestTokenVersionRevocation:
    """Validate that token_version bumping invalidates prior access JWTs."""

    async def test_token_version_bump_invalidates_prior_jwt(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After bumping token_version the old access JWT must return 401."""
        unique = uuid.uuid4().hex[:8]
        username = f"rev_bump_{unique}"
        await _create_local_user(client, admin_auth_header, username)
        tokens = await _login(client, username, STRONG_PASSWORD)
        old_access = tokens["access_token"]

        # Verify the token works before revocation.
        resp = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {old_access}"}
        )
        assert resp.status_code == 200, "token should be valid before bump"

        # Bump token_version directly via the service (simulates revoke_all_tokens).
        resp2 = await client.post("/auth/logout/", headers={"Authorization": f"Bearer {old_access}"})
        assert resp2.status_code == 204

        # The old token should now be stale.
        resp3 = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {old_access}"}
        )
        assert resp3.status_code == 401, (
            f"old token should be rejected after token_version bump, got {resp3.status_code}"
        )

    async def test_token_version_unchanged_jwt_still_valid(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """When token_version is not bumped the access JWT remains valid."""
        unique = uuid.uuid4().hex[:8]
        username = f"rev_valid_{unique}"
        await _create_local_user(client, admin_auth_header, username)
        tokens = await _login(client, username, STRONG_PASSWORD)
        access = tokens["access_token"]

        # /auth/me/ without any logout/bump — token should remain valid.
        resp = await client.get("/auth/me/", headers={"Authorization": f"Bearer {access}"})
        assert resp.status_code == 200, "token should remain valid when version not bumped"

    async def test_legacy_jwt_without_token_version_claim_rejected(
        self, client: AsyncClient
    ):
        """A JWT with no token_version claim is treated as version=0 and rejected."""
        # Build a legacy-style JWT (no token_version, no jti) for the admin user.
        from datetime import UTC, datetime, timedelta

        result_resp = await client.post(
            "/auth/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}
        )
        assert result_resp.status_code == 200
        real_payload = jwt.decode(
            result_resp.json()["access_token"],
            options={"verify_signature": False},
            algorithms=[settings.jwt_algorithm],
        )

        # Craft a new JWT with the same sub/username/exp but *without* token_version.
        now = datetime.now(UTC)
        legacy_payload = {
            "sub": real_payload["sub"],
            "username": real_payload["username"],
            "exp": now + timedelta(minutes=15),
            "iat": now,
            # Deliberately omit jti and token_version.
        }
        legacy_token = jwt.encode(
            legacy_payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        resp = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {legacy_token}"}
        )
        assert resp.status_code == 401, (
            "legacy JWT without token_version should be rejected"
        )


# ---------------------------------------------------------------------------
# Logout revocation tests
# ---------------------------------------------------------------------------


class TestLogoutRevocation:
    """POST /auth/logout/ must invalidate the prior access JWT."""

    async def test_logout_invalidates_prior_access_jwt(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After logout the access JWT used for logout should return 401 on /auth/me/."""
        unique = uuid.uuid4().hex[:8]
        username = f"logout_rev_{unique}"
        await _create_local_user(client, admin_auth_header, username)
        tokens = await _login(client, username, STRONG_PASSWORD)
        access = tokens["access_token"]

        # Confirm /auth/me/ works before logout.
        resp_before = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp_before.status_code == 200

        # Logout.
        resp_logout = await client.post(
            "/auth/logout/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp_logout.status_code == 204

        # The same access token must now be rejected.
        resp_after = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp_after.status_code == 401, (
            "access JWT must be invalidated after logout"
        )


# ---------------------------------------------------------------------------
# Change-password revocation tests
# ---------------------------------------------------------------------------


class TestChangePasswordRevocation:
    """POST /auth/change-password/ must invalidate the prior access JWT."""

    async def test_change_password_invalidates_prior_access_jwt(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After password change the old access JWT should return 401 on /auth/me/."""
        unique = uuid.uuid4().hex[:8]
        username = f"chpw_rev_{unique}"
        old_password = STRONG_PASSWORD
        new_password = "NewSecure9876!@"

        await _create_local_user(client, admin_auth_header, username, old_password)
        tokens = await _login(client, username, old_password)
        access = tokens["access_token"]

        # Confirm /auth/me/ works before password change.
        resp_before = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp_before.status_code == 200

        # Change password.
        resp_chpw = await client.post(
            "/auth/change-password/",
            json={"current_password": old_password, "new_password": new_password},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp_chpw.status_code == 204, f"Change password failed: {resp_chpw.text}"

        # The old access token must now be rejected.
        resp_after = await client.get(
            "/auth/me/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp_after.status_code == 401, (
            "old access JWT must be invalidated after password change"
        )

    async def test_change_password_new_password_usable_after_change(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After password change the user can log in with the new password.

        Regression for CR-01: if the password hash and token revocation were
        committed in separate transactions a crash between them could leave the
        user with all tokens revoked but the old password still stored, locking
        them out. This test asserts the new password is always persisted when
        change-password returns 204.
        """
        unique = uuid.uuid4().hex[:8]
        username = f"chpw_atomic_{unique}"
        old_password = STRONG_PASSWORD
        new_password = "AtomicChange5678#"

        await _create_local_user(client, admin_auth_header, username, old_password)
        tokens = await _login(client, username, old_password)
        access = tokens["access_token"]

        resp_chpw = await client.post(
            "/auth/change-password/",
            json={"current_password": old_password, "new_password": new_password},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp_chpw.status_code == 204, f"Change password failed: {resp_chpw.text}"

        # New password must work for fresh login (proves hash was committed).
        new_tokens = await _login(client, username, new_password)
        assert "access_token" in new_tokens, "Login with new password must succeed"

        # Old password must be rejected.
        resp_old = await client.post(
            "/auth/login",
            data={"username": username, "password": old_password},
        )
        assert resp_old.status_code == 401, "Old password must be rejected after change"
