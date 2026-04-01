"""Integration tests for settings admin endpoints: bulk update, reset, OAuth CRUD."""

import uuid

from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Update settings (PUT /settings/)
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    async def test_update_setting_success(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /settings/ updates a setting and returns all settings."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"ai_enabled": False}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tabs" in data

    async def test_update_unknown_key_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """PUT /settings/ with unknown key returns 400."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"nonexistent_key_xyz": "value"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "Unknown setting key" in resp.json()["detail"]

    async def test_update_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """PUT /settings/ as editor returns 403."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"ai_enabled": False}},
            headers=editor_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_unauthenticated(self, client: AsyncClient):
        """PUT /settings/ without auth returns 401."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"ai_enabled": False}},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Reset settings (POST /settings/reset/)
# ---------------------------------------------------------------------------


class TestResetSettings:
    async def test_reset_success(self, client: AsyncClient, admin_auth_header: dict):
        """POST /settings/reset/ resets settings and returns all."""
        await client.put(
            "/settings/",
            json={"settings": {"ai_enabled": False}},
            headers=admin_auth_header,
        )
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["ai_enabled"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    async def test_reset_unknown_key_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /settings/reset/ with unknown key returns 400."""
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["nonexistent_key_xyz"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    async def test_reset_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /settings/reset/ as editor returns 403."""
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["ai_enabled"]},
            headers=editor_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API key status
# ---------------------------------------------------------------------------


class TestApiKeyStatus:
    async def test_api_key_status_success(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /settings/api-key-status/ returns configured status."""
        resp = await client.get("/settings/api-key-status/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic_configured" in data
        assert "openai_configured" in data
        assert isinstance(data["anthropic_configured"], bool)

    async def test_api_key_status_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """GET /settings/api-key-status/ as editor returns 403."""
        resp = await client.get("/settings/api-key-status/", headers=editor_auth_header)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Config mode (public)
# ---------------------------------------------------------------------------


class TestConfigMode:
    async def test_config_mode_no_auth(self, client: AsyncClient):
        """GET /settings/config-mode/ returns 200 without auth."""
        resp = await client.get("/settings/config-mode/")
        assert resp.status_code == 200
        assert "env_only" in resp.json()


# ---------------------------------------------------------------------------
# OAuth provider CRUD
# ---------------------------------------------------------------------------


class TestOAuthProviderCRUD:
    async def test_list_providers(self, client: AsyncClient, admin_auth_header: dict):
        """GET /settings/oauth-providers/ returns a list."""
        resp = await client.get("/settings/oauth-providers/", headers=admin_auth_header)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_provider(self, client: AsyncClient, admin_auth_header: dict):
        """POST /settings/oauth-providers/ creates a new provider."""
        slug = f"test-oidc-{uuid.uuid4().hex[:6]}"
        provider_data = {
            "slug": slug,
            "display_name": f"Test OIDC {slug}",
            "provider_type": "oidc",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "authorize_url": "https://example.com/oauth/authorize",
            "token_url": "https://example.com/oauth/token",
            "userinfo_url": "https://example.com/oauth/userinfo",
        }
        resp = await client.post(
            "/settings/oauth-providers/",
            json=provider_data,
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == slug
        assert "id" in data
        # client_secret should not be in response
        assert "client_secret" not in data

        # Cleanup
        await client.delete(
            f"/settings/oauth-providers/{data['id']}", headers=admin_auth_header
        )

    async def test_create_provider_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /settings/oauth-providers/ as editor returns 403."""
        resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": "test",
                "display_name": "Test",
                "provider_type": "oidc",
                "client_id": "x",
                "client_secret": "x",
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_provider(self, client: AsyncClient, admin_auth_header: dict):
        """PUT /settings/oauth-providers/{id} updates a provider."""
        slug = f"update-{uuid.uuid4().hex[:6]}"
        create_resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": slug,
                "display_name": f"Update Test {slug}",
                "provider_type": "oidc",
                "client_id": "old-client-id",
                "client_secret": "old-secret",
            },
            headers=admin_auth_header,
        )
        provider_id = create_resp.json()["id"]

        resp = await client.put(
            f"/settings/oauth-providers/{provider_id}",
            json={"client_id": "new-client-id"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["client_id"] == "new-client-id"

        # Cleanup
        await client.delete(
            f"/settings/oauth-providers/{provider_id}", headers=admin_auth_header
        )

    async def test_delete_provider(self, client: AsyncClient, admin_auth_header: dict):
        """DELETE /settings/oauth-providers/{id} removes a provider."""
        slug = f"delete-{uuid.uuid4().hex[:6]}"
        create_resp = await client.post(
            "/settings/oauth-providers/",
            json={
                "slug": slug,
                "display_name": f"Delete Test {slug}",
                "provider_type": "oidc",
                "client_id": "x",
                "client_secret": "x",
            },
            headers=admin_auth_header,
        )
        provider_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/settings/oauth-providers/{provider_id}", headers=admin_auth_header
        )
        assert resp.status_code == 204

        # Verify gone
        list_resp = await client.get(
            "/settings/oauth-providers/", headers=admin_auth_header
        )
        ids = [p["id"] for p in list_resp.json()]
        assert provider_id not in ids

    async def test_delete_provider_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """DELETE /settings/oauth-providers/{random_uuid} returns 404."""
        resp = await client.delete(
            f"/settings/oauth-providers/{uuid.uuid4()}", headers=admin_auth_header
        )
        assert resp.status_code == 404
