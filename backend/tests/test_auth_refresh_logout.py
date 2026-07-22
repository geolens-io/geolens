"""Integration tests for auth refresh, logout, and config endpoints."""

import anyio
from httpx import AsyncClient

from app.core.config import settings

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


# ---------------------------------------------------------------------------
# Refresh token tests
# ---------------------------------------------------------------------------


class TestRefreshToken:
    async def test_refresh_success(self, client: AsyncClient):
        """POST /auth/refresh/ with valid refresh token returns new tokens."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post(
            "/auth/refresh/",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "expires_in" in data
        assert data["refresh_token"] != refresh_token

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """POST /auth/refresh/ with invalid token returns 401."""
        resp = await client.post(
            "/auth/refresh/",
            json={"refresh_token": "invalid-token-value"},
        )
        assert resp.status_code == 401
        assert "Invalid or expired" in resp.json()["detail"]

    async def test_refresh_empty_token(self, client: AsyncClient):
        """POST /auth/refresh/ with empty token returns 401."""
        resp = await client.post(
            "/auth/refresh/",
            json={"refresh_token": ""},
        )
        assert resp.status_code == 401

    async def test_refresh_rotates_token(self, client: AsyncClient, monkeypatch):
        """With grace disabled, rotation invalidates the old token instantly.

        fix(#621): grace_seconds=0 opts back into strict single-use rotation;
        the default grace behavior is covered by TestRotationGraceWindow.
        """
        monkeypatch.setattr(settings, "refresh_rotation_grace_seconds", 0)
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        refresh_token = login_resp.json()["refresh_token"]

        # First refresh succeeds
        resp1 = await client.post(
            "/auth/refresh/",
            json={"refresh_token": refresh_token},
        )
        assert resp1.status_code == 200

        # Reusing the old refresh token should fail (rotation)
        resp2 = await client.post(
            "/auth/refresh/",
            json={"refresh_token": refresh_token},
        )
        assert resp2.status_code == 401

    async def test_refresh_new_access_token_works(self, client: AsyncClient):
        """Access token from refresh can access /auth/me/."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post(
            "/auth/refresh/",
            json={"refresh_token": refresh_token},
        )
        new_access = resp.json()["access_token"]

        me_resp = await client.get(
            "/auth/me/",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == ADMIN_USER


# ---------------------------------------------------------------------------
# Rotation grace window (fix #621)
# ---------------------------------------------------------------------------


class TestRotationGraceWindow:
    """A just-rotated token stays usable for a short grace window so the
    losers of a concurrent multi-tab refresh race are not stranded with a
    dead credential (observed live as recurring `200+401+401` triplets)."""

    async def test_concurrent_tabs_all_get_valid_pairs(self, client: AsyncClient):
        """N callers presenting the same token inside the grace window each
        mint their OWN valid pair (short-lived family branches)."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        original = login_resp.json()["refresh_token"]

        pairs = []
        for _ in range(3):
            resp = await client.post(
                "/auth/refresh/",
                json={"refresh_token": original},
            )
            assert resp.status_code == 200
            pairs.append(resp.json())

        # Each branch got a distinct refresh token...
        assert len({p["refresh_token"] for p in pairs}) == 3
        # ...and every branch remains independently rotatable.
        for p in pairs:
            resp = await client.post(
                "/auth/refresh/",
                json={"refresh_token": p["refresh_token"]},
            )
            assert resp.status_code == 200

    async def test_reuse_after_grace_expires_is_rejected(
        self, client: AsyncClient, monkeypatch
    ):
        """Past the grace window the rotated token dies naturally (401)."""
        monkeypatch.setattr(settings, "refresh_rotation_grace_seconds", 1)
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        original = login_resp.json()["refresh_token"]

        resp1 = await client.post(
            "/auth/refresh/",
            json={"refresh_token": original},
        )
        assert resp1.status_code == 200

        await anyio.sleep(1.2)

        resp2 = await client.post(
            "/auth/refresh/",
            json={"refresh_token": original},
        )
        assert resp2.status_code == 401

    async def test_logout_revokes_in_grace_tokens(self, client: AsyncClient):
        """Explicit revocation is instant: logout kills the in-grace token
        AND its successor — the grace window never survives a hard logout."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        access = login_resp.json()["access_token"]
        original = login_resp.json()["refresh_token"]

        rotated = await client.post(
            "/auth/refresh/",
            json={"refresh_token": original},
        )
        successor = rotated.json()["refresh_token"]

        logout_resp = await client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert logout_resp.status_code == 204

        for token in (original, successor):
            resp = await client.post(
                "/auth/refresh/",
                json={"refresh_token": token},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout tests
# ---------------------------------------------------------------------------


class TestLogout:
    async def test_logout_success(self, client: AsyncClient):
        """POST /auth/logout/ with valid token returns 204."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        token = login_resp.json()["access_token"]

        resp = await client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

    async def test_logout_unauthenticated(self, client: AsyncClient):
        """POST /auth/logout/ without auth returns 401."""
        resp = await client.post("/auth/logout/")
        assert resp.status_code == 401

    async def test_logout_revokes_refresh_tokens(self, client: AsyncClient):
        """After logout, refresh tokens are invalidated."""
        login_resp = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
        token = login_resp.json()["access_token"]
        refresh_token = login_resp.json()["refresh_token"]

        await client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.post(
            "/auth/refresh/",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auth config tests
# ---------------------------------------------------------------------------


class TestAuthConfig:
    async def test_config_no_auth_required(self, client: AsyncClient):
        """GET /auth/config/ returns 200 without auth."""
        resp = await client.get("/auth/config/")
        assert resp.status_code == 200
        data = resp.json()
        assert "registration_enabled" in data
        assert isinstance(data["registration_enabled"], bool)
