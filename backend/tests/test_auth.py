"""Integration tests for auth flow, RBAC, and admin user management.

These tests run against a real database via httpx ASGITransport. The FastAPI
app's lifespan handler seeds roles and an initial admin user on startup.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied

If the database is not available, tests will fail with a connection error.
"""

import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient

from app.auth.router import REGISTRATION_ENABLED
from app.config import settings
from tests.conftest import get_auth_header

# Admin credentials from settings (geolens_admin_username/password)
ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user_via_admin(
    client: AsyncClient,
    admin_headers: dict,
    username: str,
    password: str = "testpass123",
    role: str = "viewer",
    email: str | None = None,
) -> dict:
    """Create a user through the admin endpoint and return the response JSON."""
    body = {"username": username, "password": password, "role": role}
    if email is not None:
        body["email"] = email
    resp = await client.post("/admin/users/", json=body, headers=admin_headers)
    assert resp.status_code == 201, f"Create user failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    async def test_register_when_enabled(self, client: AsyncClient, monkeypatch):
        """Registration creates a pending user when REGISTRATION_ENABLED=true."""
        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )

        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={"username": f"reguser_{unique}", "password": "securepass123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "message" in data
        assert "awaiting" in data["message"].lower()

    async def test_register_when_disabled(self, client: AsyncClient):
        """Registration is blocked when registration is disabled (default)."""
        resp = await client.post(
            "/auth/register/",
            json={"username": "shouldfail", "password": "securepass123"},
        )
        assert resp.status_code == 403

    async def test_register_duplicate_username(self, client: AsyncClient, monkeypatch):
        """Duplicate username returns 409 Conflict."""
        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )

        unique = uuid.uuid4().hex[:8]
        username = f"dupuser_{unique}"
        # First registration
        resp1 = await client.post(
            "/auth/register/",
            json={"username": username, "password": "securepass123"},
        )
        assert resp1.status_code == 201

        # Second registration with same username
        resp2 = await client.post(
            "/auth/register/",
            json={"username": username, "password": "securepass123"},
        )
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        """Seeded admin user can log in and receives a JWT token."""
        resp = await client.post(
            "/auth/login/",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_sets_last_login_at(self, client: AsyncClient):
        """Successful login populates last_login_at on the user profile."""
        # Login
        resp = await client.post(
            "/auth/login/",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        # Check /auth/me for last_login_at
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/auth/me/", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["last_login_at"] is not None

    async def test_login_wrong_password(self, client: AsyncClient):
        """Wrong password returns 401."""
        resp = await client.post(
            "/auth/login/",
            data={"username": ADMIN_USER, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Nonexistent username returns 401."""
        resp = await client.post(
            "/auth/login/",
            data={"username": "nonexistent_user_xyz", "password": "anypass123"},
        )
        assert resp.status_code == 401

    async def test_login_deactivated_user(self, client: AsyncClient):
        """Deactivated user cannot log in (returns 403 Account not active)."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        # Create a user, then deactivate them
        unique = uuid.uuid4().hex[:8]
        username = f"deactuser_{unique}"
        user_data = await _create_user_via_admin(
            client, admin_headers, username=username, password="testpass123"
        )
        user_id = user_data["id"]

        # Deactivate
        resp = await client.post(
            f"/admin/users/{user_id}/deactivate/", headers=admin_headers
        )
        assert resp.status_code == 200

        # Try to log in -- deactivated users get 403
        resp = await client.post(
            "/auth/login/",
            data={"username": username, "password": "testpass123"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Account not active"


# ---------------------------------------------------------------------------
# Token / me tests
# ---------------------------------------------------------------------------


class TestTokenMe:
    async def test_me_with_valid_token(self, client: AsyncClient):
        """GET /auth/me returns user profile with roles when authenticated."""
        headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        resp = await client.get("/auth/me/", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == ADMIN_USER
        assert "admin" in data["roles"]
        assert data["is_active"] is True
        assert "last_login_at" in data

    async def test_me_without_token(self, client: AsyncClient):
        """GET /auth/me without Authorization header returns 401."""
        resp = await client.get("/auth/me/")
        assert resp.status_code == 401

    async def test_me_with_invalid_token(self, client: AsyncClient):
        """GET /auth/me with garbage token returns 401."""
        resp = await client.get(
            "/auth/me/", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_admin_can_access_admin_endpoints(self, client: AsyncClient):
        """Admin user can access /admin/users."""
        headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        resp = await client.get("/admin/users/", headers=headers)
        assert resp.status_code == 200

    async def test_viewer_cannot_access_admin_endpoints(self, client: AsyncClient):
        """Viewer user gets 403 on /admin/users."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"viewer_{unique}"
        await _create_user_via_admin(
            client,
            admin_headers,
            username=username,
            password="testpass123",
            role="viewer",
        )

        viewer_headers = await get_auth_header(client, username, "testpass123")
        resp = await client.get("/admin/users/", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_editor_cannot_access_admin_endpoints(self, client: AsyncClient):
        """Editor user gets 403 on /admin/users."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"editor_{unique}"
        await _create_user_via_admin(
            client,
            admin_headers,
            username=username,
            password="testpass123",
            role="editor",
        )

        editor_headers = await get_auth_header(client, username, "testpass123")
        resp = await client.get("/admin/users/", headers=editor_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin user names endpoint
# ---------------------------------------------------------------------------


class TestAdminUserNames:
    async def test_returns_id_and_username(self, client: AsyncClient):
        """GET /admin/users/names returns lightweight user list."""
        headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        resp = await client.get("/admin/users/names/", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # Check shape
        item = data[0]
        assert "id" in item
        assert "username" in item
        # Should not include heavy fields
        assert "password_hash" not in item
        assert "roles" not in item
        assert "email" not in item

    async def test_requires_admin(self, client: AsyncClient):
        """Viewer cannot access /admin/users/names."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        unique = uuid.uuid4().hex[:8]
        await _create_user_via_admin(
            client, admin_headers, username=f"viewer_{unique}", role="viewer"
        )
        viewer_headers = await get_auth_header(
            client, f"viewer_{unique}", "testpass123"
        )
        resp = await client.get("/admin/users/names/", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_unauthenticated(self, client: AsyncClient):
        """Unauthenticated request returns 401."""
        resp = await client.get("/admin/users/names/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin user management tests
# ---------------------------------------------------------------------------


class TestAdminUserManagement:
    async def test_admin_create_user(self, client: AsyncClient):
        """Admin can create a user with a specified role."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"newuser_{unique}"
        resp = await client.post(
            "/admin/users/",
            json={
                "username": username,
                "password": "testpass123",
                "role": "editor",
                "email": f"{username}@test.com",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == username
        assert "editor" in data["roles"]
        assert data["email"] == f"{username}@test.com"
        assert data["is_active"] is True

    async def test_admin_deactivate_user(self, client: AsyncClient):
        """Admin can deactivate a user."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"todeact_{unique}"
        user_data = await _create_user_via_admin(
            client, admin_headers, username=username
        )
        user_id = user_data["id"]

        resp = await client.post(
            f"/admin/users/{user_id}/deactivate/", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_admin_list_users(self, client: AsyncClient):
        """Admin can list users with pagination."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        resp = await client.get("/admin/users/", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "total" in data
        assert isinstance(data["users"], list)
        assert data["total"] >= 1  # At least the admin user

    async def test_admin_get_user(self, client: AsyncClient):
        """Admin can get a specific user by ID."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"getuser_{unique}"
        user_data = await _create_user_via_admin(
            client, admin_headers, username=username
        )
        user_id = user_data["id"]

        resp = await client.get(f"/admin/users/{user_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == username

    async def test_admin_update_user_role(self, client: AsyncClient):
        """Admin can change a user's role."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        unique = uuid.uuid4().hex[:8]
        username = f"rolechange_{unique}"
        user_data = await _create_user_via_admin(
            client, admin_headers, username=username, role="viewer"
        )
        user_id = user_data["id"]
        assert "viewer" in user_data["roles"]

        resp = await client.patch(
            f"/admin/users/{user_id}",
            json={"role": "editor"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "editor" in resp.json()["roles"]

    async def test_admin_get_nonexistent_user_returns_404(self, client: AsyncClient):
        """Getting a nonexistent user returns 404."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/admin/users/{fake_id}", headers=admin_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin approve / reject user tests
# ---------------------------------------------------------------------------


class TestAdminApproveReject:
    async def test_admin_approve_pending_user(self, client: AsyncClient, monkeypatch):
        """Admin can approve a pending user via POST /admin/users/{id}/approve/."""
        from app.auth.router import REGISTRATION_ENABLED
        from unittest.mock import AsyncMock

        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )

        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        # Register a pending user
        unique = uuid.uuid4().hex[:8]
        username = f"pendapprove_{unique}"
        reg_resp = await client.post(
            "/auth/register/",
            json={"username": username, "password": "securepass123"},
        )
        assert reg_resp.status_code == 201

        # Find the user via admin list
        list_resp = await client.get(
            "/admin/users/?status=pending",
            headers=admin_headers,
        )
        assert list_resp.status_code == 200
        users = list_resp.json()["users"]
        pending_user = next(u for u in users if u["username"] == username)
        user_id = pending_user["id"]

        # Approve with viewer role
        approve_resp = await client.post(
            f"/admin/users/{user_id}/approve/",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert approve_resp.status_code == 200
        data = approve_resp.json()
        assert data["status"] == "active"
        assert data["is_active"] is True
        assert "viewer" in data["roles"]

    async def test_admin_reject_pending_user(self, client: AsyncClient, monkeypatch):
        """Admin can reject a pending user via POST /admin/users/{id}/reject/."""
        from app.auth.router import REGISTRATION_ENABLED
        from unittest.mock import AsyncMock

        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )

        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        # Register a pending user
        unique = uuid.uuid4().hex[:8]
        username = f"pendreject_{unique}"
        reg_resp = await client.post(
            "/auth/register/",
            json={"username": username, "password": "securepass123"},
        )
        assert reg_resp.status_code == 201

        # Find the user
        list_resp = await client.get(
            "/admin/users/?status=pending",
            headers=admin_headers,
        )
        assert list_resp.status_code == 200
        users = list_resp.json()["users"]
        pending_user = next(u for u in users if u["username"] == username)
        user_id = pending_user["id"]

        # Reject (hard-delete)
        reject_resp = await client.post(
            f"/admin/users/{user_id}/reject/",
            headers=admin_headers,
        )
        assert reject_resp.status_code == 204

        # Confirm user is gone
        get_resp = await client.get(
            f"/admin/users/{user_id}",
            headers=admin_headers,
        )
        assert get_resp.status_code == 404

    async def test_approve_forbidden_for_non_admin(self, client: AsyncClient):
        """Non-admin user cannot approve a pending user (returns 403)."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        # Create a viewer
        unique = uuid.uuid4().hex[:8]
        viewer_username = f"viewer_{unique}"
        await _create_user_via_admin(
            client, admin_headers, username=viewer_username, role="viewer"
        )
        viewer_headers = await get_auth_header(client, viewer_username, "testpass123")

        # Viewer tries to approve a user (use a fake ID — auth check happens first)
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/admin/users/{fake_id}/approve/",
            json={"role": "viewer"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    async def test_reject_forbidden_for_non_admin(self, client: AsyncClient):
        """Non-admin user cannot reject a pending user (returns 403)."""
        admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

        # Create an editor
        unique = uuid.uuid4().hex[:8]
        editor_username = f"editor_{unique}"
        await _create_user_via_admin(
            client, admin_headers, username=editor_username, role="editor"
        )
        editor_headers = await get_auth_header(client, editor_username, "testpass123")

        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/admin/users/{fake_id}/reject/",
            headers=editor_headers,
        )
        assert resp.status_code == 403
