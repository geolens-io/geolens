"""SSO login-mode tests for Phase 1236 Plan 02 (SSO-01/02/03/04).

Covers:
  - password_login_enabled=false → non-admin POST /auth/login → 403 (SSO-01)
  - password_login_enabled=false → manage_settings admin login → 200 (SSO-02, break-glass)
  - password_login_enabled=true (default) → all users can log in
  - GET /auth/config exposes password_login_enabled and reflects the configured value (SSO-03)
  - PUT /settings with password_login_enabled=false and zero enabled providers → 422 (SSO-04)
  - PUT /settings with password_login_enabled=false after enabling a provider → 200 (SSO-04)
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique(prefix: str = "u") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _set_password_login_enabled(
    client: AsyncClient, header: dict, enabled: bool
) -> None:
    """PUT /settings/ to configure password_login_enabled."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"password_login_enabled": enabled}},
        headers=header,
    )
    assert resp.status_code == 200, (
        f"Failed to set password_login_enabled={enabled}: {resp.text}"
    )


async def _reset_password_login_enabled(client: AsyncClient, header: dict) -> None:
    """Restore password_login_enabled to the default (True) after a test."""
    await _set_password_login_enabled(client, header, True)


async def _create_viewer(client: AsyncClient, admin_header: dict) -> tuple[str, str]:
    """Create a viewer-role user via admin API and return (username, password)."""
    username = _unique("sso_viewer")
    password = "TestPass1234!"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": "viewer"},
        headers=admin_header,
    )
    assert resp.status_code == 201, f"Failed to create viewer: {resp.text}"
    return username, password


async def _make_enabled_oauth_provider(db: AsyncSession) -> OAuthProvider:
    """Insert a minimal enabled OAuthProvider row for lockout-guard tests."""
    provider = OAuthProvider(
        slug=f"test-{uuid.uuid4().hex[:8]}",
        display_name="Test SSO Provider",
        provider_type="oidc",
        client_id="test-client-id",
        client_secret_encrypted=encrypt_secret("placeholder-secret"),
        discovery_url="https://test.example.com/.well-known/openid-configuration",
        scopes="openid email profile",
        default_role="viewer",
        enabled=True,
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


async def _delete_provider(db: AsyncSession, provider: OAuthProvider) -> None:
    """Remove a test OAuthProvider row."""
    await db.delete(provider)
    await db.flush()


# ---------------------------------------------------------------------------
# Tests: SSO-01/SSO-02 — password_login_enabled gate + break-glass
# ---------------------------------------------------------------------------


class TestPasswordLoginEnabledGate:
    async def test_non_admin_login_rejected_when_flag_off(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """SSO-01: non-admin POST /auth/login → 403 when password_login_enabled=false."""
        username, password = await _create_viewer(client, admin_auth_header)
        # We need an enabled provider so the lockout guard lets us flip the flag.
        provider = await _make_enabled_oauth_provider(test_db_session)
        await test_db_session.commit()
        try:
            await _set_password_login_enabled(client, admin_auth_header, False)
            resp = await client.post(
                "/auth/login",
                data={"username": username, "password": password},
            )
            assert resp.status_code == 403, (
                f"Expected 403 for non-admin with password_login_enabled=false, "
                f"got {resp.status_code}: {resp.text}"
            )
            assert (
                "SSO provider" in resp.json()["detail"]
                or "disabled" in resp.json()["detail"]
            )
        finally:
            await _reset_password_login_enabled(client, admin_auth_header)
            await _delete_provider(test_db_session, provider)
            await test_db_session.commit()

    async def test_admin_break_glass_login_succeeds_when_flag_off(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """SSO-02: manage_settings admin can still POST /auth/login when flag is false (break-glass)."""
        from app.core.config import settings as app_settings

        admin_username = app_settings.geolens_admin_username
        admin_password = app_settings.geolens_admin_password.get_secret_value()

        provider = await _make_enabled_oauth_provider(test_db_session)
        await test_db_session.commit()
        try:
            await _set_password_login_enabled(client, admin_auth_header, False)
            resp = await client.post(
                "/auth/login",
                data={"username": admin_username, "password": admin_password},
            )
            assert resp.status_code == 200, (
                f"Admin break-glass failed with password_login_enabled=false: "
                f"{resp.status_code}: {resp.text}"
            )
            assert "access_token" in resp.json()
        finally:
            await _reset_password_login_enabled(client, admin_auth_header)
            await _delete_provider(test_db_session, provider)
            await test_db_session.commit()

    async def test_non_admin_login_succeeds_when_flag_on(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Default (password_login_enabled=true): non-admin password login succeeds."""
        username, password = await _create_viewer(client, admin_auth_header)
        # Explicitly set to True (already the default; belt-and-suspenders).
        await _set_password_login_enabled(client, admin_auth_header, True)
        resp = await client.post(
            "/auth/login",
            data={"username": username, "password": password},
        )
        assert resp.status_code == 200, (
            f"Expected 200 with password_login_enabled=true, "
            f"got {resp.status_code}: {resp.text}"
        )
        assert "access_token" in resp.json()


# ---------------------------------------------------------------------------
# Tests: SSO-03 — GET /auth/config exposes password_login_enabled
# ---------------------------------------------------------------------------


class TestAuthConfigPasswordLoginEnabled:
    async def test_config_returns_password_login_enabled_true_by_default(
        self, client: AsyncClient
    ) -> None:
        """SSO-03: GET /auth/config returns password_login_enabled=true by default."""
        resp = await client.get("/auth/config/")
        assert resp.status_code == 200
        data = resp.json()
        assert "password_login_enabled" in data, (
            "password_login_enabled missing from /auth/config response"
        )
        assert data["password_login_enabled"] is True

    async def test_config_reflects_updated_value(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """SSO-03: GET /auth/config reflects the configured value after PUT /settings/."""
        provider = await _make_enabled_oauth_provider(test_db_session)
        await test_db_session.commit()
        try:
            await _set_password_login_enabled(client, admin_auth_header, False)
            resp = await client.get("/auth/config/")
            assert resp.status_code == 200
            assert resp.json()["password_login_enabled"] is False
        finally:
            await _reset_password_login_enabled(client, admin_auth_header)
            await _delete_provider(test_db_session, provider)
            await test_db_session.commit()


# ---------------------------------------------------------------------------
# Tests: SSO-04 — lockout guard on PUT /settings
# ---------------------------------------------------------------------------


class TestPasswordLoginLockoutGuard:
    async def test_disabling_password_login_with_zero_providers_returns_422(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """SSO-04: PUT /settings with password_login_enabled=false and no enabled providers → 422."""
        # Confirm there are no enabled providers in the test DB.
        # The default test fixture has no OAuth providers configured.
        resp = await client.put(
            "/settings/",
            json={"settings": {"password_login_enabled": False}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, (
            f"Expected 422 (lockout guard), got {resp.status_code}: {resp.text}"
        )
        detail = resp.json()["detail"]
        assert (
            "SSO provider" in detail
            or "OAuth provider" in detail
            or "provider" in detail.lower()
        ), f"422 detail should mention providers: {detail}"

    async def test_disabling_password_login_with_enabled_provider_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """SSO-04: PUT /settings with password_login_enabled=false and >=1 enabled provider → 200."""
        provider = await _make_enabled_oauth_provider(test_db_session)
        await test_db_session.commit()
        try:
            resp = await client.put(
                "/settings/",
                json={"settings": {"password_login_enabled": False}},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, (
                f"Expected 200 with enabled provider, got {resp.status_code}: {resp.text}"
            )
            # Verify the setting was persisted
            config_resp = await client.get("/auth/config/")
            assert config_resp.json()["password_login_enabled"] is False
        finally:
            await _reset_password_login_enabled(client, admin_auth_header)
            await _delete_provider(test_db_session, provider)
            await test_db_session.commit()

    async def test_lockout_guard_does_not_block_enabling_password_login(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """SSO-04: PUT /settings with password_login_enabled=true always succeeds (no lockout)."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"password_login_enabled": True}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, (
            f"Expected 200 for enabling password login, got {resp.status_code}: {resp.text}"
        )
