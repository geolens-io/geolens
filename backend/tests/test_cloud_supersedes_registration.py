"""Tests for CLOUD-03: /auth/register closure when the cloud overlay is active.

Enforces the CLOUD-03 "replacing" directive:
  - When has_extension("cloud") is True → POST /auth/register returns 403
    (global-scoped self-signup is CLOSED; ONLY /cloud/signup/register is valid)
  - When has_extension("cloud") is False → /auth/register behaves exactly as
    today (REGISTRATION_ENABLED-gated) — byte-identical community/enterprise path
  - seed_initial_admin still seeds the fleet superadmin on a fresh DB, cloud or not

References: CLOUD-03, T-1211-22 (EoP - global registration left open in cloud mode)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.modules.auth.router import REGISTRATION_ENABLED


# ---------------------------------------------------------------------------
# Registry isolation fixture (mirrors test_openapi_overlay_boundary pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_extension_registry():
    """Reset the extension registry before and after each test.

    Prevents installed overlays (enterprise editable-install) from polluting
    the has_extension() checks. Mirrors _clean_extension_registry fixture in
    test_openapi_overlay_boundary.py.
    """
    import app.platform.extensions as ext_mod

    # Save current state
    saved_extensions = dict(ext_mod._extensions)
    saved_routers = list(ext_mod._routers)
    saved_loaded = ext_mod._loaded
    saved_slot_owners = dict(ext_mod._slot_owners)

    # Clear for test isolation
    ext_mod._extensions.clear()
    ext_mod._loaded = False
    ext_mod._routers.clear()
    ext_mod._slot_owners.clear()

    yield

    # Restore
    ext_mod._extensions.clear()
    ext_mod._extensions.update(saved_extensions)
    ext_mod._routers.clear()
    ext_mod._routers.extend(saved_routers)
    ext_mod._loaded = saved_loaded
    ext_mod._slot_owners.clear()
    ext_mod._slot_owners.update(saved_slot_owners)


def _set_cloud_active(active: bool) -> None:
    """Set or clear the 'cloud' extension in the registry."""
    import app.platform.extensions as ext_mod
    from unittest.mock import MagicMock

    if active:
        ext_mod._extensions["cloud"] = (
            MagicMock()
        )  # sentinel — just needs to be present
    else:
        ext_mod._extensions.pop("cloud", None)


# ---------------------------------------------------------------------------
# Tests: cloud overlay ACTIVE — /auth/register is CLOSED
# ---------------------------------------------------------------------------


class TestCloudActiveRegistrationClosed:
    """When has_extension("cloud") is True, POST /auth/register returns 403."""

    async def test_register_closed_when_cloud_active(self, client: AsyncClient):
        """POST /auth/register → 403 when the cloud overlay is active (T-1211-22).

        The ONLY signup route is /cloud/signup/register.
        """
        _set_cloud_active(True)

        resp = await client.post(
            "/auth/register/",
            json={"username": "shouldbeblocked", "password": "SecurePass123!"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 (cloud gate closed), got {resp.status_code}: {resp.text}"
        )
        # Response must point users to the tenant signup path
        body = resp.json()
        assert (
            "cloud" in body.get("detail", "").lower()
            or "tenant" in body.get("detail", "").lower()
        ), f"403 detail should reference the tenant signup path; got: {body}"

    async def test_register_no_trailing_slash_closed_when_cloud_active(
        self, client: AsyncClient
    ):
        """POST /auth/register (no trailing slash) is ALSO closed when cloud is active.

        Both ROUTE-01 variants must be gated — not just the canonical slash form.
        """
        _set_cloud_active(True)

        resp = await client.post(
            "/auth/register",
            json={"username": "shouldbeblocked2", "password": "SecurePass123!"},
        )
        # Both slash and no-slash variants share the same handler; both must 403
        assert resp.status_code == 403, (
            f"Expected 403 for /auth/register (no slash); got {resp.status_code}: {resp.text}"
        )

    async def test_no_user_row_created_when_cloud_active(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """When cloud is active, POST /auth/register creates ZERO user rows.

        T-1211-22: the gate must fire BEFORE any DB write — a 403 must not
        create an orphan pending user.
        """
        _set_cloud_active(True)

        # POST /auth/register — must be blocked (403) by cloud gate
        resp = await client.post(
            "/auth/register/",
            json={"username": "cloud_gate_no_row_user", "password": "SecurePass123!"},
        )
        assert resp.status_code == 403, (
            f"Cloud gate must block /auth/register; got {resp.status_code}: {resp.text}"
        )

        # Verify via admin user-list that the user was NOT created
        list_resp = await client.get(
            "/admin/users/",
            params={"search": "cloud_gate_no_row_user"},
            headers=admin_auth_header,
        )
        assert list_resp.status_code == 200
        users_data = list_resp.json()
        items = (
            users_data.get("items", users_data)
            if isinstance(users_data, dict)
            else users_data
        )
        matching = [
            u
            for u in (items if isinstance(items, list) else [])
            if u.get("username") == "cloud_gate_no_row_user"
        ]
        assert len(matching) == 0, (
            f"Cloud gate must prevent user row creation; found {len(matching)} rows"
        )

    async def test_register_when_registration_enabled_still_403_with_cloud(
        self, client: AsyncClient, monkeypatch
    ):
        """Cloud gate takes priority over REGISTRATION_ENABLED.

        Even if REGISTRATION_ENABLED=True AND cloud is active, /auth/register is
        CLOSED. The cloud gate is checked BEFORE REGISTRATION_ENABLED.
        """
        _set_cloud_active(True)

        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),  # enabled, but cloud takes priority
        )

        resp = await client.post(
            "/auth/register/",
            json={"username": "should_still_be_blocked", "password": "SecurePass123!"},
        )
        assert resp.status_code == 403, (
            f"Cloud gate must override REGISTRATION_ENABLED=True; "
            f"got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Tests: cloud overlay ABSENT — /auth/register byte-identical (T-1211-22)
# ---------------------------------------------------------------------------


class TestCloudAbsentRegistrationUnchanged:
    """When has_extension("cloud") is False, /auth/register is byte-identical to today."""

    async def test_register_disabled_when_cloud_absent(self, client: AsyncClient):
        """With cloud absent, disabled registration still returns 403 (unchanged)."""
        _set_cloud_active(False)
        # REGISTRATION_ENABLED defaults to False in the test suite

        resp = await client.post(
            "/auth/register/",
            json={"username": "cloudabsent_disabled", "password": "SecurePass123!"},
        )
        assert resp.status_code == 403

    async def test_register_enabled_when_cloud_absent(
        self, client: AsyncClient, monkeypatch
    ):
        """With cloud absent and registration enabled, /auth/register returns 201 (unchanged)."""
        _set_cloud_active(False)

        monkeypatch.setattr(
            REGISTRATION_ENABLED,
            "get",
            AsyncMock(return_value=True),
        )

        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={
                "username": f"cloudabsent_enabled_{unique}",
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 201, (
            f"With cloud absent and REGISTRATION_ENABLED=True, /auth/register should "
            f"return 201; got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "message" in data
        assert "awaiting" in data["message"].lower()


# ---------------------------------------------------------------------------
# Tests: seed_initial_admin still runs regardless of cloud overlay presence
# ---------------------------------------------------------------------------


class TestSeedInitialAdminUnbroken:
    """seed_initial_admin (first-boot fleet superadmin seed) must not be broken.

    seed_initial_admin is keyed on user_count==0 and creates the fleet superadmin.
    It is NOT a public self-serve signup path — it's a one-time bootstrap.
    The cloud gate must NOT disable or alter it.
    """

    async def test_seed_initial_admin_function_exists(self):
        """seed_initial_admin function is importable and is NOT patched out."""
        from app.api.main import seed_initial_admin

        assert callable(seed_initial_admin), "seed_initial_admin must remain callable"

    async def test_seed_initial_admin_is_not_gated_by_cloud(self):
        """seed_initial_admin does NOT call has_extension and is NOT cloud-gated.

        The cloud gate is in auth/router.py register() — NOT in seed_initial_admin.
        This test verifies that seed_initial_admin's source does not reference
        has_extension, preserving the first-boot superadmin flow.
        """
        import inspect
        from app.api.main import seed_initial_admin

        source = inspect.getsource(seed_initial_admin)
        assert "has_extension" not in source, (
            "seed_initial_admin must NOT call has_extension() — the cloud gate "
            "belongs in auth/router.py register(), not in the first-boot seed"
        )
