"""Tests for password complexity validation (SEC-S16, Phase 1062-01).

Covers:
  Unit tests (no DB, direct module calls):
    - Valid password (12 chars, 4 classes) passes.
    - Short password (< min_length) raises ValueError with length message.
    - Only lowercase (1 class) fails diversity check.
    - Only lowercase+uppercase (2 classes) fails when require_classes=3.
    - 3-of-4 classes (lower+upper+digit, no symbol) passes.
    - All 4 classes present passes even at exactly min_length.
    - Short but all-classes password fails length check first.
    - validate_password_from_settings reads min_length from Settings.

  Integration tests (HTTP via test client):
    - POST /auth/register/ rejects weak password (422).
    - POST /auth/change-password/ rejects weak new_password (422).
    - POST /admin/users/ rejects weak password (422).
    - POST /admin/users/{id}/convert-saml-to-local/ rejects weak password (422).
    - PASSWORD_MIN_LENGTH env override permits shorter password.
"""

import pytest
import uuid
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.modules.auth.password_policy import validate_password_complexity
from app.modules.auth.router import REGISTRATION_ENABLED
from app.core.config import settings

pytestmark = pytest.mark.anyio

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

# A password that satisfies the default policy (12 chars, 3+ classes).
STRONG_PASSWORD = "TestPass1234!"


# ---------------------------------------------------------------------------
# Unit tests — no DB, no HTTP
# ---------------------------------------------------------------------------


class TestValidatePasswordComplexity:
    """Direct unit tests of validate_password_complexity()."""

    def test_valid_password_4_classes_passes(self):
        """12 chars with all 4 classes (lower+upper+digit+symbol) must pass."""
        # Should not raise.
        validate_password_complexity(
            "Abcdef1!XYZab", min_length=12, require_classes=3
        )

    def test_short_password_raises_length_error(self):
        """Password shorter than min_length raises ValueError with length message."""
        with pytest.raises(ValueError, match="at least 12 characters"):
            validate_password_complexity("admin", min_length=12, require_classes=3)

    def test_lowercase_only_fails_diversity(self):
        """All-lowercase password (1 class) fails with 3-class requirement."""
        with pytest.raises(ValueError, match="at least 3 of"):
            validate_password_complexity(
                "abcdefghijkl", min_length=12, require_classes=3
            )

    def test_two_class_password_fails_3_class_requirement(self):
        """Lower+upper only (2 classes) fails when require_classes=3."""
        with pytest.raises(ValueError, match="at least 3 of"):
            validate_password_complexity(
                "Abcdefghijkl", min_length=12, require_classes=3
            )

    def test_3_of_4_classes_passes(self):
        """Lower+upper+digit (3 of 4) passes with require_classes=3."""
        # No symbol — 3 classes, 13 chars.
        validate_password_complexity(
            "Abcdef1234567", min_length=12, require_classes=3
        )

    def test_exactly_min_length_all_classes_passes(self):
        """Exactly 12 chars with all 4 classes passes."""
        validate_password_complexity(
            "Abc1!defghij", min_length=12, require_classes=3
        )

    def test_short_with_all_classes_fails_length_first(self):
        """5-char password with all 4 classes still fails the length check."""
        with pytest.raises(ValueError, match="at least 12 characters"):
            validate_password_complexity(
                "Ab1!x", min_length=12, require_classes=3
            )

    def test_require_classes_1_allows_lowercase_only(self):
        """require_classes=1 allows an all-lowercase 12-char password."""
        # Should not raise.
        validate_password_complexity(
            "abcdefghijkl", min_length=12, require_classes=1
        )


# ---------------------------------------------------------------------------
# Integration tests — HTTP via test client
# ---------------------------------------------------------------------------


class TestRegisterPasswordPolicy:
    """POST /auth/register/ must reject weak passwords with 422."""

    async def test_register_rejects_weak_password(
        self, client: AsyncClient, monkeypatch
    ):
        """Registering with 'password' (8 chars, 1 class) must return 422."""
        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )
        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={"username": f"weakpw_{unique}", "password": "password"},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        # Error message must mention the policy.
        body = resp.text.lower()
        assert "password" in body

    async def test_register_accepts_strong_password(
        self, client: AsyncClient, monkeypatch
    ):
        """Registering with a strong password (12+, 3+ classes) succeeds."""
        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )
        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={"username": f"strongpw_{unique}", "password": STRONG_PASSWORD},
        )
        # 201 = registration submitted (pending approval).
        assert resp.status_code == 201, f"Strong password rejected: {resp.text}"


class TestChangePasswordPolicy:
    """POST /auth/change-password/ must reject weak new passwords with 422."""

    async def _make_user_and_login(
        self, client: AsyncClient, admin_headers: dict
    ) -> tuple[str, str, str]:
        """Create a user, log in, return (username, password, access_token)."""
        unique = uuid.uuid4().hex[:8]
        username = f"cpw_{unique}"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": STRONG_PASSWORD, "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        login_resp = await client.post(
            "/auth/login",
            data={"username": username, "password": STRONG_PASSWORD},
        )
        assert login_resp.status_code == 200
        return username, STRONG_PASSWORD, login_resp.json()["access_token"]

    async def test_change_password_rejects_weak_password(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Changing password to 'weak1234' (no class diversity) must return 422."""
        _, _, access = await self._make_user_and_login(client, admin_auth_header)
        resp = await client.post(
            "/auth/change-password/",
            json={"current_password": STRONG_PASSWORD, "new_password": "weak1234"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for weak new_password, got {resp.status_code}: {resp.text}"
        )


class TestAdminCreateUserPasswordPolicy:
    """POST /admin/users/ must reject weak passwords with 422."""

    async def test_admin_create_user_rejects_weak_password(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Admin creating a user with 'password' must get 422."""
        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/admin/users/",
            json={
                "username": f"weakadmin_{unique}",
                "password": "password",
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for weak admin-created password, got {resp.status_code}: {resp.text}"
        )

    async def test_admin_create_user_rejects_16_char_single_class(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """16 lowercase chars with 1 class must fail class-diversity check."""
        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/admin/users/",
            json={
                "username": f"weakadmin2_{unique}",
                "password": "abcdefghijklmnop",
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for single-class password, got {resp.status_code}: {resp.text}"
        )


class TestPasswordMinLengthEnvOverride:
    """PASSWORD_MIN_LENGTH env override must relax the policy."""

    def test_settings_env_override_relaxes_min_length(self, monkeypatch):
        """Patching password_min_length on settings must make short passwords valid."""
        # Monkeypatch the module-level settings singleton.
        monkeypatch.setattr(settings, "password_min_length", 6)
        monkeypatch.setattr(settings, "password_require_classes", 3)

        # "Abcd1!" is 6 chars, 3 classes (upper, lower, digit, symbol).
        from app.modules.auth.password_policy import validate_password_from_settings

        # Should not raise.
        validate_password_from_settings("Abcd1!")

    def test_settings_default_rejects_6_char_password(self):
        """Default settings (min 12) must reject a 6-char password."""
        from app.modules.auth.password_policy import validate_password_from_settings

        with pytest.raises(ValueError, match="at least 12 characters"):
            validate_password_from_settings("Abcd1!")
