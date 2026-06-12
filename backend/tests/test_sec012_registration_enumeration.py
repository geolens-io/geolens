"""Regression tests for SEC-012: registration response enumeration.

A collision on username or email must return the SAME status code and response
body shape as a brand-new registration — no 400/409/distinguishable signal.

Test pattern: RED before fix (409 on collision), GREEN after fix (201 uniform).
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TCH002 — used in fixture type hints

from app.modules.auth.models import User
from app.modules.auth.router import REGISTRATION_ENABLED


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique(prefix: str = "sectest") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _register(
    client: AsyncClient,
    username: str,
    password: str = "SecurePass123!",
    email: str | None = None,
):
    body: dict = {"username": username, "password": password}
    if email is not None:
        body["email"] = email
    return await client.post("/auth/register/", json=body)


# ---------------------------------------------------------------------------
# SEC-012: uniform response on collision
# ---------------------------------------------------------------------------


class TestSec012UniformRegistrationResponse:
    """Registration must return identical status+body whether new or colliding."""

    async def test_new_username_returns_201(self, client: AsyncClient, monkeypatch):
        """Baseline: a truly new username returns 201 with a pending message."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        resp = await _register(client, _unique("new"))
        assert resp.status_code == 201
        data = resp.json()
        assert "message" in data
        assert "awaiting" in data["message"].lower()

    async def test_duplicate_username_returns_same_status_as_new(
        self, client: AsyncClient, monkeypatch
    ):
        """SEC-012: a duplicate username must return 201, not 409/400.

        This test FAILS before the fix (router raises 409 Conflict on ValueError
        from register_user) and PASSES after (uniform pending response).
        """
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        username = _unique("dup_user")

        # First registration — genuine new account
        resp1 = await _register(client, username)
        assert resp1.status_code == 201

        # Second registration with same username — must NOT expose collision
        resp2 = await _register(client, username)
        assert resp2.status_code == 201, (
            f"SEC-012: duplicate username returned {resp2.status_code} "
            f"instead of 201 — registration enumeration possible"
        )
        data = resp2.json()
        assert "message" in data
        assert "awaiting" in data["message"].lower(), (
            "Response body must be the uniform pending-approval message"
        )

    async def test_duplicate_email_returns_same_status_as_new(
        self, client: AsyncClient, monkeypatch
    ):
        """SEC-012: a duplicate email must return 201, not 409/400."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        email = f"{_unique('em')}@example.com"
        user1 = _unique("emaildup1")
        user2 = _unique("emaildup2")

        # First registration with that email
        resp1 = await _register(client, user1, email=email)
        assert resp1.status_code == 201

        # Second registration with same email, different username
        resp2 = await _register(client, user2, email=email)
        assert resp2.status_code == 201, (
            f"SEC-012: duplicate email returned {resp2.status_code} "
            f"instead of 201 — email enumeration possible"
        )
        data = resp2.json()
        assert "message" in data

    async def test_collision_does_not_create_duplicate_row(
        self, client: AsyncClient, monkeypatch, test_db_session: AsyncSession
    ):
        """SEC-012: on a username collision no extra DB row must be created."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        username = _unique("nodedup")

        # First registration creates exactly one row
        resp1 = await _register(client, username)
        assert resp1.status_code == 201

        result = await test_db_session.execute(
            select(func.count()).where(func.lower(User.username) == username.lower())
        )
        count_before = result.scalar_one()
        assert count_before == 1, "New registration must create exactly one user row"

        # Collision attempt — must NOT insert a second row
        resp2 = await _register(client, username)
        assert resp2.status_code == 201  # uniform response

        result2 = await test_db_session.execute(
            select(func.count()).where(func.lower(User.username) == username.lower())
        )
        count_after = result2.scalar_one()
        assert count_after == 1, (
            f"Collision created an extra row (count={count_after}); expected 1"
        )

    async def test_new_registration_still_creates_row(
        self, client: AsyncClient, monkeypatch, test_db_session: AsyncSession
    ):
        """Happy path: a genuinely new username creates exactly one DB row."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        username = _unique("happypath")

        result_before = await test_db_session.execute(
            select(func.count()).where(func.lower(User.username) == username.lower())
        )
        assert result_before.scalar_one() == 0, "Pre-condition: user must not exist"

        resp = await _register(client, username)
        assert resp.status_code == 201

        result_after = await test_db_session.execute(
            select(func.count()).where(func.lower(User.username) == username.lower())
        )
        assert result_after.scalar_one() == 1, (
            "New registration must create exactly one row"
        )
