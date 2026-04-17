"""Tests for the granular permissions system (PERM-01, PERM-03, PERM-04, PERM-05)."""

import pytest


# ---------------------------------------------------------------------------
# Task 1: Permissions module, PersistentConfig key, defaults
# ---------------------------------------------------------------------------


class TestDefaultPermissions:
    """PERM-01: Default permission matrix matches current role behavior."""

    def test_default_permissions_viewer(self):
        from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS

        viewer = DEFAULT_ROLE_PERMISSIONS["viewer"]
        assert viewer["export"] is True
        assert viewer["upload"] is False
        assert viewer["create_layers"] is False
        assert viewer["edit_metadata"] is False
        assert viewer["manage_collections"] is False
        assert viewer["manage_users"] is False
        assert viewer["manage_settings"] is False

    def test_default_permissions_editor(self):
        from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS

        editor = DEFAULT_ROLE_PERMISSIONS["editor"]
        assert editor["upload"] is True
        assert editor["create_layers"] is True
        assert editor["export"] is True
        assert editor["edit_metadata"] is True
        assert editor["manage_collections"] is True
        assert editor["use_ai_chat"] is True
        assert editor["manage_users"] is False
        assert editor["manage_settings"] is False

    def test_default_permissions_admin(self):
        from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS

        admin = DEFAULT_ROLE_PERMISSIONS["admin"]
        for cap in admin.values():
            assert cap is True

    def test_all_capabilities_complete(self):
        from app.modules.auth.permissions import ALL_CAPABILITIES

        assert len(ALL_CAPABILITIES) == 8
        expected = {
            "upload",
            "create_layers",
            "export",
            "edit_metadata",
            "manage_collections",
            "use_ai_chat",
            "manage_users",
            "manage_settings",
        }
        assert set(ALL_CAPABILITIES) == expected


class TestGetEffectivePermissions:
    """get_effective_permissions() reads from PersistentConfig, merges with defaults."""

    @pytest.mark.anyio
    async def test_get_effective_permissions_defaults(self, client, test_db_session):
        """When no DB override exists, returns DEFAULT_ROLE_PERMISSIONS."""
        from app.modules.auth.permissions import (
            DEFAULT_ROLE_PERMISSIONS,
            get_effective_permissions,
        )

        result = await get_effective_permissions(test_db_session)
        assert result == DEFAULT_ROLE_PERMISSIONS

    @pytest.mark.anyio
    async def test_get_effective_permissions_override(
        self, client, admin_auth_header, test_db_session
    ):
        """After setting custom matrix via settings API, get_effective_permissions returns merged result."""
        from app.modules.auth.permissions import get_effective_permissions

        # Override: give viewer upload=True
        custom = {
            "viewer": {
                "upload": True,
                "create_layers": False,
                "export": True,
                "edit_metadata": False,
                "manage_collections": False,
                "use_ai_chat": False,
                "manage_users": False,
                "manage_settings": False,
            },
            "editor": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": False,
                "manage_settings": False,
            },
            "admin": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": True,
                "manage_settings": True,
            },
        }
        resp = await client.put(
            "/settings/",
            json={"settings": {"role_permissions": custom}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        result = await get_effective_permissions(test_db_session)
        assert result["viewer"]["upload"] is True

        # Cleanup: reset to defaults
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["role_permissions"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200


class TestSettingsIntegration:
    """Admin can GET/PUT role_permissions via settings API."""

    @pytest.mark.anyio
    async def test_get_put_permissions(self, client, admin_auth_header):
        """Admin can see role_permissions in settings and update them."""
        # GET all settings should include permissions tab
        resp = await client.get("/settings/all/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "permissions" in data["tabs"]
        perm_items = data["tabs"]["permissions"]
        keys = [item["key"] for item in perm_items]
        assert "role_permissions" in keys

        # PUT to update viewer export to False (but keep admin caps intact)
        custom = {
            "viewer": {
                "upload": False,
                "create_layers": False,
                "export": False,
                "edit_metadata": False,
                "manage_collections": False,
                "use_ai_chat": False,
                "manage_users": False,
                "manage_settings": False,
            },
            "editor": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": False,
                "manage_settings": False,
            },
            "admin": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": True,
                "manage_settings": True,
            },
        }
        resp = await client.put(
            "/settings/",
            json={"settings": {"role_permissions": custom}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        # Verify it stuck
        resp = await client.get("/settings/all/", headers=admin_auth_header)
        data = resp.json()
        perm_items = data["tabs"]["permissions"]
        rp = next(i for i in perm_items if i["key"] == "role_permissions")
        assert rp["value"]["viewer"]["export"] is False
        assert rp["source"] == "overridden"

        # Cleanup
        await client.post(
            "/settings/reset/",
            json={"keys": ["role_permissions"]},
            headers=admin_auth_header,
        )

    @pytest.mark.anyio
    async def test_admin_lockout_prevention(self, client, admin_auth_header):
        """PUT that removes admin.manage_users or admin.manage_settings is rejected."""
        # Try to remove manage_users from admin
        bad_matrix = {
            "viewer": {
                "upload": False,
                "create_layers": False,
                "export": True,
                "edit_metadata": False,
                "manage_collections": False,
                "use_ai_chat": False,
                "manage_users": False,
                "manage_settings": False,
            },
            "editor": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": False,
                "manage_settings": False,
            },
            "admin": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": False,
                "manage_settings": True,
            },
        }
        resp = await client.put(
            "/settings/",
            json={"settings": {"role_permissions": bad_matrix}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422  # validation error

        # Also try removing manage_settings
        bad_matrix["admin"]["manage_users"] = True
        bad_matrix["admin"]["manage_settings"] = False
        resp = await client.put(
            "/settings/",
            json={"settings": {"role_permissions": bad_matrix}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Task 2: require_permission() factory and /auth/me/permissions endpoint
# ---------------------------------------------------------------------------


class TestRequirePermission:
    """PERM-03: require_permission() dependency factory."""

    @pytest.mark.anyio
    async def test_me_permissions_endpoint(
        self, client, admin_auth_header, editor_auth_header, viewer_auth_header
    ):
        """GET /auth/me/permissions returns effective permissions for each role."""
        # Admin should have all True
        resp = await client.get("/auth/me/permissions/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "permissions" in data
        perms = data["permissions"]
        assert len(perms) == 8
        for cap, val in perms.items():
            assert val is True, f"Admin should have {cap}=True"

        # Editor should have upload=True, manage_users=False
        resp = await client.get("/auth/me/permissions/", headers=editor_auth_header)
        assert resp.status_code == 200
        perms = resp.json()["permissions"]
        assert perms["upload"] is True
        assert perms["manage_users"] is False
        assert perms["manage_settings"] is False

        # Viewer should have export=True, upload=False
        resp = await client.get("/auth/me/permissions/", headers=viewer_auth_header)
        assert resp.status_code == 200
        perms = resp.json()["permissions"]
        assert perms["export"] is True
        assert perms["upload"] is False

    @pytest.mark.anyio
    async def test_permissions_update_reflected(
        self, client, admin_auth_header, viewer_auth_header
    ):
        """After admin updates permissions, /auth/me/permissions reflects new values."""
        # Give viewer upload=True
        custom = {
            "viewer": {
                "upload": True,
                "create_layers": False,
                "export": True,
                "edit_metadata": False,
                "manage_collections": False,
                "use_ai_chat": False,
                "manage_users": False,
                "manage_settings": False,
            },
            "editor": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": False,
                "manage_settings": False,
            },
            "admin": {
                "upload": True,
                "create_layers": True,
                "export": True,
                "edit_metadata": True,
                "manage_collections": True,
                "use_ai_chat": True,
                "manage_users": True,
                "manage_settings": True,
            },
        }
        resp = await client.put(
            "/settings/",
            json={"settings": {"role_permissions": custom}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        # Viewer should now have upload=True
        resp = await client.get("/auth/me/permissions/", headers=viewer_auth_header)
        assert resp.status_code == 200
        perms = resp.json()["permissions"]
        assert perms["upload"] is True

        # Cleanup
        await client.post(
            "/settings/reset/",
            json={"keys": ["role_permissions"]},
            headers=admin_auth_header,
        )
